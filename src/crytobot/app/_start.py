"""Hazırlık ve başlatmanın depo kapıları (spec 0022 R-1, R-3, R-4, R-5, R-9; plan Risk 8, 12).

Depoyu yalnız hazırlık oluşturur, başlatma asla: silinmiş bir depo drawdown durdurmasını sessizce
sıfırlayamaz (BR-6). Her ikisi de yalnız paper'dır; live depo "mod uyuşmuyor" ile reddedilir.
Hazırlık tur atmaz ve borsaya çıkmaz. Depo dosyası hiçbir durumda otomatik silinmez.

Canlı depo ağa bağlıdır (spec 0041 CB-4): `prepare --live` ve `start --live` depoyu kayıtlı
ağından başka bir ağla açmaz; denetim borsaya çıkan kimlik/yetki adımından önce yapılır.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from crytobot.execution import (
    LIVE,
    PAPER,
    BinanceLiveClient,
    ExecutionError,
    LiveExchange,
    load_credentials,
)
from crytobot.persistence import (
    MAINNET,
    StartRecord,
    StoreOutcome,
    append_start_record,
    bind_network,
    create_store,
    load_store,
    save_store,
)
from crytobot.portfolio import EMPTY_LEDGER, LedgerOutcome, open_ledger

PREPARE_HINT = "önce hazırlık: python -m crytobot prepare"
LIVE_PREPARE_HINT = "önce hazırlık: python -m crytobot prepare --live"
# spec 0036 R-13: the old file is never deleted by the bot; the owner moves it aside
OUTDATED_HINT = "eski depo dosyasını kenara alıp python -m crytobot prepare --live ile yeniden açın"


class PrepareOutcome(Enum):
    PREPARED = "prepared"
    INVALID_BALANCE = "invalid_balance"
    STORE_EXISTS = "store_exists"
    NETWORK_MISMATCH = "network_mismatch"
    CREATE_FAILED = "create_failed"
    BALANCE_NOT_WRITTEN = "balance_not_written"


@dataclass(frozen=True)
class PrepareResult:
    outcome: PrepareOutcome
    message: str


def prepare_store(store_path: str, opening_balance: Decimal, now: datetime) -> PrepareResult:
    """R-3: depo yoksa paper deposunu oluşturur ve açılış bakiyesini yazar.

    Bakiye depo oluşmadan önce denenir; var olan depoya (okunabilir olsun ya da olmasın) hiçbir şey
    yazılmaz. Oluşturmadan sonra kayıt reddedilirse dosya yerinde kalır (plan Risk 12): başlatma onu
    "defter açılmamış" ile reddeder.
    """
    opened = open_ledger(EMPTY_LEDGER, opening_balance, now)
    if opened.outcome is not LedgerOutcome.OPENED:
        return PrepareResult(PrepareOutcome.INVALID_BALANCE, "açılış bakiyesi geçersiz")
    created = create_store(store_path, PAPER)
    if created.outcome is StoreOutcome.ALREADY_EXISTS:
        return PrepareResult(PrepareOutcome.STORE_EXISTS, "depo zaten var; hiçbir şey yazılmadı")
    if created.state is None:
        message = f"depo oluşturulamadı: {created.message}"
        return PrepareResult(PrepareOutcome.CREATE_FAILED, message)
    state = created.state
    saved = save_store(store_path, state, opened.ledger, state.execution, state.risk)
    if saved.state is None:
        message = f"depo oluştu, açılış bakiyesi yazılamadı: {saved.message}"
        return PrepareResult(PrepareOutcome.BALANCE_NOT_WRITTEN, message)
    return PrepareResult(PrepareOutcome.PREPARED, f"paper deposu hazır: {opened.message}")


class StartOutcome(Enum):
    READY = "ready"
    STORE_MISSING = "store_missing"
    STORE_UNREADABLE = "store_unreadable"
    STORE_BUSY = "store_busy"
    MODE_MISMATCH = "mode_mismatch"
    LEDGER_NOT_OPENED = "ledger_not_opened"
    LIVE_STORE_OUTDATED = "live_store_outdated"
    START_NOT_RECORDED = "start_not_recorded"
    NETWORK_MISMATCH = "network_mismatch"


@dataclass(frozen=True)
class StartCheck:
    """`hint` depo yokken (R-4) ve canlı depo eskiyken (spec 0036 R-13) doludur."""

    outcome: StartOutcome
    message: str
    hint: str | None


_REFUSALS = {
    StoreOutcome.NOT_FOUND: StartOutcome.STORE_MISSING,
    StoreOutcome.BUSY: StartOutcome.STORE_BUSY,
    StoreOutcome.MODE_MISMATCH: StartOutcome.MODE_MISMATCH,
    StoreOutcome.LIVE_STORE_OUTDATED: StartOutcome.LIVE_STORE_OUTDATED,
}


def open_for_start(store_path: str, mode: str = PAPER) -> StartCheck:
    """R-4, R-5: depo belirtilen modda ve defter açıksa `READY`; değilse nedeni. Yazmaz."""
    loaded = load_store(store_path, mode)
    if loaded.state is None:
        outcome = _REFUSALS.get(loaded.outcome, StartOutcome.STORE_UNREADABLE)
        if outcome is StartOutcome.MODE_MISMATCH:
            message = f"MODE_MISMATCH (depo {mode} modunda değil)"
        else:
            message = loaded.message
        hint = None
        if outcome is StartOutcome.STORE_MISSING:
            hint = PREPARE_HINT if mode == PAPER else LIVE_PREPARE_HINT
        elif outcome is StartOutcome.LIVE_STORE_OUTDATED:
            hint = OUTDATED_HINT
        return StartCheck(outcome, f"başlatma reddedildi: {message}", hint)
    if loaded.state.ledger.balance is None:
        hint = None if mode == PAPER else LIVE_PREPARE_HINT
        return StartCheck(
            StartOutcome.LEDGER_NOT_OPENED, "başlatma reddedildi: defter açılmamış", hint
        )
    return StartCheck(StartOutcome.READY, "depo hazır", None)


START_NOT_RECORDED = "başlatma reddedildi: başlatma kaydı yazılamadı"


def record_start(
    store_path: str,
    *,
    trial: bool,
    report_path: str | None,
    now: datetime,
    report_sha256: str | None = None,
) -> StartCheck:
    """Spec 0038 CB-1, plan Risk 6: paper başlatmasını depoya yazar; depo `READY` olduktan sonra,
    tur atılmadan çağrılır. `--trial` "deneme"dir, raporu yoktur; kanıtlı başlatmanın raporu
    mutlak yoldur (çözümü `__main__` yapar) ve kapının onayladığı parmak izini taşır (spec 0040
    CB-5). Yazılamazsa başlatma reddedilir: kaydı olmayan bir koşu kanıt sayılamaz."""
    record = StartRecord(
        now,
        trial,
        None if trial else report_path,
        report_sha256=None if trial else report_sha256,
    )
    written = append_start_record(store_path, record)
    if written.outcome is not StoreOutcome.SAVED:
        return StartCheck(StartOutcome.START_NOT_RECORDED, START_NOT_RECORDED, None)
    return StartCheck(StartOutcome.READY, "başlatma kaydedildi", None)


def read_pairs(whitelist: Sequence[str], store_path: str, mode: str = PAPER) -> tuple[str, ...]:
    """R-9: beyaz liste ve açık pozisyonların çiftleri, sırayla ve tekrarsız (plan Risk 8).

    Depo yüklenemezse yalnız beyaz liste; depo sorununu tur kendisi bildirir.
    """
    loaded = load_store(store_path, mode)
    held: tuple[str, ...] = ()
    if loaded.state is not None:
        held = tuple(position.pair for position in loaded.state.ledger.positions.values())
    return tuple(dict.fromkeys((*whitelist, *held)))


def _network_name(testnet: bool) -> str:
    return "testnet" if testnet else MAINNET


def store_network_problem(store_path: str, testnet: bool, *, readonly: bool = True) -> str | None:
    """Spec 0041 CB-4: var olan canlı deponun kayıtlı ağı ayardakinden farklıysa ret metni.

    Yazmaz, borsaya çıkmaz; `start --live`'da kilitten önce salt okunur çağrılır (plan Risk 4).
    Depo yoksa ya da canlı depo olarak okunamıyorsa denetim geçer: o reddi depo kapısı adıyla
    verir; ağ, kilit altında tur atılmadan `bind_live_network` ile yine denetlenir."""
    loaded = load_store(store_path, LIVE, readonly=readonly)
    if loaded.state is None:
        return None
    wanted = _network_name(testnet)
    if loaded.state.network != wanted:
        return f"depo ağı uyuşmuyor: depo={loaded.state.network} ayar={wanted}"
    return None


def bind_live_network(store_path: str, testnet: bool) -> StartCheck:
    """Spec 0041 CB-4, G-1: kilit alınıp depo `READY` olduktan sonra, ilk turdan önce: canlı
    deponun ağı eksikse yazılır (kaydı olmayan depo mainnet'tir), farklıysa başlatma reddedilir."""
    bound = bind_network(store_path, _network_name(testnet))
    if bound.outcome is StoreOutcome.SAVED:
        return StartCheck(StartOutcome.READY, bound.message, None)
    if bound.outcome is StoreOutcome.NETWORK_MISMATCH:
        message = f"başlatma reddedildi: {bound.message}"
        return StartCheck(StartOutcome.NETWORK_MISMATCH, message, None)
    message = f"başlatma reddedildi: depo ağı yazılamadı: {bound.message}"
    return StartCheck(StartOutcome.START_NOT_RECORDED, message, None)


def prepare_live_store(
    store_path: str,
    now: datetime,
    *,
    testnet: bool = False,
    live_client: object = None,
    env: Mapping[str, str] | None = None,
    env_file: str | None = None,
) -> PrepareResult:
    """Spec 0033 R-2: Canlı depoyu borsadan serbest USDT bakiyesiyle oluşturur ve defteri açar.

    Spec 0041 CB-4 (plan Risk 3): depo zaten varsa borsaya hiç çıkılmaz: önce ağ uyuşmazlığı,
    sonra "depo zaten var" reddi. Hazırlık kilit altındadır, depo `mode=rw` okunur (sıcak günlük).
    Yeni depo ayardaki ağa bağlı açılır."""
    mismatch = store_network_problem(store_path, testnet, readonly=False)
    if mismatch is not None:
        return PrepareResult(PrepareOutcome.NETWORK_MISMATCH, mismatch)
    if load_store(store_path, LIVE).outcome is not StoreOutcome.NOT_FOUND:
        return PrepareResult(PrepareOutcome.STORE_EXISTS, "depo zaten var; hiçbir şey yazılmadı")
    try:
        real_client = live_client if isinstance(live_client, BinanceLiveClient) else None
        if real_client is None:
            creds = load_credentials(testnet=testnet, env=env, env_file=env_file)
            real_client = BinanceLiveClient(creds)
        real_client.verify_permissions()
        balance = real_client.fetch_free_balance(asset="USDT")
    except ExecutionError as err:
        return PrepareResult(PrepareOutcome.CREATE_FAILED, f"borsa hazırlık hatası: {err}")

    if balance <= Decimal(0):
        return PrepareResult(
            PrepareOutcome.INVALID_BALANCE,
            f"borsa serbest USDT bakiyesi pozitif değil ({balance}); canlı depo açılamaz",
        )

    opened = open_ledger(EMPTY_LEDGER, balance, now)
    if opened.outcome is not LedgerOutcome.OPENED:
        return PrepareResult(PrepareOutcome.INVALID_BALANCE, "açılış bakiyesi geçersiz")

    created = create_store(store_path, LIVE, _network_name(testnet))
    if created.outcome is StoreOutcome.ALREADY_EXISTS:
        return PrepareResult(PrepareOutcome.STORE_EXISTS, "depo zaten var; hiçbir şey yazılmadı")
    if created.state is None:
        return PrepareResult(
            PrepareOutcome.CREATE_FAILED, f"depo oluşturulamadı: {created.message}"
        )

    state = created.state
    saved = save_store(store_path, state, opened.ledger, state.execution, state.risk)
    if saved.state is None:
        return PrepareResult(
            PrepareOutcome.BALANCE_NOT_WRITTEN,
            f"depo oluştu, açılış bakiyesi yazılamadı: {saved.message}",
        )
    return PrepareResult(PrepareOutcome.PREPARED, f"canlı depo hazır (bakiye: {balance} USDT)")


def create_live_exchange(
    testnet: bool = False,
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | None = None,
    client: object = None,
    store_path: str | None = None,
) -> tuple[LiveExchange | None, str | None]:
    """Spec 0033 R-5: Canlı borsa adaptörünü kimlik ve yetki kapılarıyla başlatır.

    Spec 0041 CB-4: `store_path` verilirse deponun ağı kimlik yüklenmeden ve borsaya çıkılmadan
    önce denetlenir; uyuşmazlıkta istemci kurulmaz."""
    if store_path is not None:
        mismatch = store_network_problem(store_path, testnet)
        if mismatch is not None:
            return None, mismatch
    try:
        real_client = client if isinstance(client, BinanceLiveClient) else None
        if real_client is None:
            creds = load_credentials(testnet=testnet, env=env, env_file=env_file)
            real_client = BinanceLiveClient(creds)
        real_client.verify_permissions()
        return LiveExchange(real_client), None
    except ExecutionError as err:
        return None, str(err)
