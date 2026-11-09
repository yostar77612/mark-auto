"""Built-in concept groups (seed version 1); user reference data only, never a trading input."""

from dataclasses import dataclass

SEED_VERSION = 1


@dataclass(frozen=True)
class ConceptGroup:
    id: str
    name: str
    codes: tuple[str, ...]


BUILTIN_GROUPS = (
    ConceptGroup('builtin.ai_server', 'AI 伺服器', ('2317', '2382', '3231', '6669', '2356', '2376', '3706', '8210', '2059')),
    ConceptGroup('builtin.adv_packaging', '先進封裝（CoWoS／FOPLP）', ('2330', '3711', '3131', '3583', '6187', '2467', '6640', '1560', '3680', '3481')),
    ConceptGroup('builtin.cooling', '散熱', ('3017', '3324', '2421', '3653', '6230', '8996', '3338')),
    ConceptGroup('builtin.power', '電源／BBU', ('2308', '2301', '6409', '3015', '6412')),
    ConceptGroup('builtin.cpo', '矽光子／CPO', ('3363', '4979', '3081', '3450', '6442', '4977', '2455', '3163', '6451')),
    ConceptGroup('builtin.ai_pcb', 'AI PCB／CCL', ('2383', '6274', '6213', '2368', '3037', '8046', '3189', '3044', '2313')),
    ConceptGroup('builtin.asic', 'ASIC／矽智財', ('3661', '3443', '3035', '6643', '3529', '6533')),
    ConceptGroup('builtin.memory', '記憶體', ('2408', '2344', '2337', '3260', '8299', '4967', '3006', '8271')),
    ConceptGroup('builtin.robotics', '機器人', ('2049', '1590', '4583', '2359', '8374', '1597', '4576')),
    ConceptGroup('builtin.grid', '重電／電網', ('1519', '1503', '1513', '1514', '1504', '1609')),
    ConceptGroup('builtin.networking', '網通／交換器', ('2345', '6285', '3596', '5388', '4906', '3380')),
    ConceptGroup('builtin.leo_satellite', '低軌衛星', ('3491', '2313', '6285', '2314', '3105')),
    ConceptGroup('builtin.defense_drone', '軍工／無人機', ('2634', '8033', '2645', '5222', '5371', '6753')),
    ConceptGroup('builtin.apple', '蘋果供應鏈', ('2317', '4938', '3008', '2474', '4958')),
    ConceptGroup('builtin.container_shipping', '貨櫃航運', ('2603', '2609', '2615')),
    ConceptGroup('builtin.ic_design', 'IC 設計大型股', ('2454', '3034', '2379', '6415', '3227')),
    ConceptGroup('builtin.panel', '面板', ('3481', '2409', '6116')),
)
