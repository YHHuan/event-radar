"""各來源 collector。每個獨立、fail-soft,回傳 raw event dict list。"""
from .accupass import collect as accupass_collect
from .culture_tw import collect as culture_tw_collect
from .era_kham import collect as era_kham_collect
from .eventbrite import collect as eventbrite_collect
from .indievox import collect as indievox_collect
from .kktix import collect as kktix_collect
from .opentix import collect as opentix_collect
from .tixcraft import collect as tixcraft_collect

COLLECTORS = {
    "culture_tw": culture_tw_collect,
    "opentix": opentix_collect,
    "kktix": kktix_collect,
    "accupass": accupass_collect,
    "indievox": indievox_collect,
    "tixcraft": tixcraft_collect,
    "era_kham": era_kham_collect,
    "eventbrite": eventbrite_collect,
}
