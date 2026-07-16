"""
Loader do ficheiro .fmd FARSITE/BehavePlus standard.

Estrutura do .fmd (versão FARSITE 4+):
- Linha 1: cabeçalho "FUEL_MODEL_FILE" ou comentário
- Linhas com FMNum FMCode 1H 10H 100H LiveH LiveW [type] 1HSAV LiveHSAV LiveWSAV Depth XtMoist DHt LHt FMName

Devolve modelos num formato preparado para a wildfire_ROS_models.

Os valores de carga (1H/10H/100H/LiveH/LiveW) em `data/fuel_models_pt.csv`
são cópia directa da Tabela 2 de Fernandes & Loureiro, "Modelos de
combustível florestal para Portugal" (UTAD/CITAB, 2021) — confirmado
número a número (ex. FM223/M-EUC: 8.36/3.81/0/4.51 t/ha vs. 8.37/3.81/
0.00/4.51 t/ha na tabela; FM211/F-EUC: 4.64/2.96/1.28/1.12 vs. 4.63/2.96/
1.27/1.12). Essa tabela declara explicitamente "Cargas em t/ha" — **não**
ton/acre. Depth/XtMoist/PC também batem certo com a tabela (t/ha e m).

As unidades nativas do .fmd genérico são:
- Loading: tons/acre (English) ou t/ha (metric) — depende do header
- SAV: 1/ft (English) ou 1/cm (metric)
- Depth: ft ou cm
- Heat: BTU/lb ou kJ/kg

Os dados deste CSV estão em formato MISTO típico do BehavePlus 5:
- Loading em t/ha (metric) — corrigido; era erradamente assumido ton/acre
- SAV/Depth/Heat em métrico
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


# Constantes de conversão para SI internas
INV_CM_TO_INV_M = 100.0
CM_TO_M = 0.01
KJ_PER_KG_TO_J_PER_KG = 1000.0

# Conversões para English (formato esperado pela wildfire_ROS_models)
INV_CM_TO_INV_FT = 30.48
CM_TO_FT = 0.0328084
T_HA_TO_LB_FT2 = 0.0204816
KJ_KG_TO_BTU_LB = 0.4299


@dataclass
class FuelModelPT:
    """
    Modelo de combustível PT.

    Mantemos duas versões dos parâmetros: nativos (como vieram do .fmd, mistos)
    e English Units puras (para passar à wildfire_ROS_models).
    """
    num: int
    code: str
    name: str
    is_dynamic: bool

    # English Units (formato wildfire_ROS_models / BehavePlus interno)
    load_1h: float          # lb/ft²
    load_10h: float         # lb/ft²
    load_100h: float        # lb/ft²
    load_live_h: float      # lb/ft² (herbáceo vivo)
    load_live_w: float      # lb/ft² (lenhoso vivo)
    sav_1h: float           # 1/ft
    sav_live_h: float       # 1/ft
    sav_live_w: float       # 1/ft
    depth: float            # ft
    moist_ext_dead: float   # fração (0-1)
    heat_dead: float        # BTU/lb
    heat_live: float        # BTU/lb

    # SI para diagnósticos e front-end (cargas em t/ha são reconhecíveis para PT)
    @property
    def load_total_dead_t_ha(self) -> float:
        return (self.load_1h + self.load_10h + self.load_100h) * 4882.43

    @property
    def load_total_live_t_ha(self) -> float:
        return (self.load_live_h + self.load_live_w) * 4882.43

    @property
    def depth_cm(self) -> float:
        return self.depth * 30.48

    @property
    def has_live_fuel(self) -> bool:
        return (self.load_live_h + self.load_live_w) > 0

    @property
    def is_empty(self) -> bool:
        return (self.load_1h + self.load_10h + self.load_100h
                + self.load_live_h + self.load_live_w) == 0


def load_fuel_models_csv(path: str | Path) -> dict[int, FuelModelPT]:
    """
    Carrega os modelos de um CSV no formato dos dados PT.

    Converte tudo para English Units (formato wildfire_ROS_models).
    """
    path = Path(path)
    models: dict[int, FuelModelPT] = {}

    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            num = int(row["FMNum"])

            # t/ha → lb/ft² (Fernandes & Loureiro 2021, Tabela 2 — ver docstring)
            load_1h = float(row["1H_FL"]) * T_HA_TO_LB_FT2
            load_10h = float(row["10H_FL"]) * T_HA_TO_LB_FT2
            load_100h = float(row["100H_FL"]) * T_HA_TO_LB_FT2
            load_live_h = float(row["LiveH_FL"]) * T_HA_TO_LB_FT2
            load_live_w = float(row["LiveW_FL"]) * T_HA_TO_LB_FT2

            # 1/cm → 1/ft
            sav_1h = float(row["1HSAV"]) * INV_CM_TO_INV_FT
            sav_live_h = float(row["LiveHSAV"]) * INV_CM_TO_INV_FT
            sav_live_w = float(row["LiveWSAV"]) * INV_CM_TO_INV_FT

            # cm → ft
            depth = float(row["Depth"]) * CM_TO_FT

            # kJ/kg → BTU/lb
            heat_dead = float(row["DHt"]) * KJ_KG_TO_BTU_LB
            heat_live = float(row["LHt"]) * KJ_KG_TO_BTU_LB

            models[num] = FuelModelPT(
                num=num,
                code=row["FMCode"],
                name=row["FMCode"],  # podemos mapear nomes Fernandes depois
                is_dynamic=(row["FMType"].strip().lower() == "dynamic"),
                load_1h=load_1h,
                load_10h=load_10h,
                load_100h=load_100h,
                load_live_h=load_live_h,
                load_live_w=load_live_w,
                sav_1h=sav_1h,
                sav_live_h=sav_live_h,
                sav_live_w=sav_live_w,
                depth=depth,
                moist_ext_dead=float(row["XtMoist"]) / 100.0,
                heat_dead=heat_dead,
                heat_live=heat_live,
            )

    return models


def load_fuel_models_fmd(path: str | Path) -> dict[int, FuelModelPT]:
    """
    Carrega modelos diretamente de um ficheiro .fmd FARSITE.

    Formato esperado por linha (após header):
    FMNum FMCode 1H 10H 100H LiveH LiveW Type 1HSAV LiveHSAV LiveWSAV Depth XtMoist DHt LHt [FMName]

    NOTA: o parsing exato depende da versão do .fmd. Adapta-se quando tivermos
    o ficheiro real para confirmar separadores e ordem.
    """
    path = Path(path)
    models: dict[int, FuelModelPT] = {}

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("FUEL"):
                continue
            parts = line.split()
            if len(parts) < 15:
                continue
            try:
                num = int(parts[0])
            except ValueError:
                continue

            code = parts[1]
            load_1h_ta = float(parts[2])
            load_10h_ta = float(parts[3])
            load_100h_ta = float(parts[4])
            load_live_h_ta = float(parts[5])
            load_live_w_ta = float(parts[6])
            fmtype = parts[7]
            sav_1h_cm = float(parts[8])
            sav_live_h_cm = float(parts[9])
            sav_live_w_cm = float(parts[10])
            depth_cm = float(parts[11])
            xt_moist_pct = float(parts[12])
            dht_kj = float(parts[13])
            lht_kj = float(parts[14])
            name = " ".join(parts[15:]) if len(parts) > 15 else code

            models[num] = FuelModelPT(
                num=num,
                code=code,
                name=name,
                is_dynamic=(fmtype.strip().lower() == "dynamic"),
                load_1h=load_1h_ta / 21.78,
                load_10h=load_10h_ta / 21.78,
                load_100h=load_100h_ta / 21.78,
                load_live_h=load_live_h_ta / 21.78,
                load_live_w=load_live_w_ta / 21.78,
                sav_1h=sav_1h_cm * INV_CM_TO_INV_FT,
                sav_live_h=sav_live_h_cm * INV_CM_TO_INV_FT,
                sav_live_w=sav_live_w_cm * INV_CM_TO_INV_FT,
                depth=depth_cm * CM_TO_FT,
                moist_ext_dead=xt_moist_pct / 100.0,
                heat_dead=dht_kj * KJ_KG_TO_BTU_LB,
                heat_live=lht_kj * KJ_KG_TO_BTU_LB,
            )

    return models


def to_wildfire_ros_dict(fm: FuelModelPT) -> dict:
    """
    Converte FuelModelPT para o formato dict esperado pela wildfire_ROS_models
    no modelo RothermelAndrews2018.

    Os nomes das chaves seguem a convenção da biblioteca (ver fuels_database.py).
    """
    return {
        "fuel_model_number": fm.num,
        "code": fm.code,
        "name": fm.name,
        # cargas em lb/ft²
        "w0_1h": fm.load_1h,
        "w0_10h": fm.load_10h,
        "w0_100h": fm.load_100h,
        "w0_lh": fm.load_live_h,
        "w0_lw": fm.load_live_w,
        # SAV em 1/ft
        "sigma_1h": fm.sav_1h,
        "sigma_lh": fm.sav_live_h,
        "sigma_lw": fm.sav_live_w,
        # outros
        "delta": fm.depth,           # ft
        "Mx": fm.moist_ext_dead,     # fração
        "h_dead": fm.heat_dead,      # BTU/lb
        "h_live": fm.heat_live,      # BTU/lb
        "dynamic": fm.is_dynamic,
    }
