"""The synthetic vehicle catalog (§6.1, §9).

A plausible sketch of the Indonesian market, not a real catalog. Base OTR
prices are in IDR at the `BASE_OTR_YEAR` price level and are order-of-magnitude
realistic so that residual ratios land in a sensible range - they are not
quoted prices.

Structure mirrors the production catalog hierarchy:
    Brand -> Model -> Generation (year range) -> Variant (trim + transmission)

Every variant carries a `code`, standing in for the manufacturer type code
that appears in the STNK `tipe` field instead of a readable trim name. That
mismatch is the whole reason the variant catalog exists, so the generator
reproduces it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BASE_OTR_YEAR = 2024


@dataclass(frozen=True)
class VariantSpec:
    trim: str
    transmission: str          # MT | AT | CVT
    #: Manufacturer type code, as it appears in the STNK `tipe` field.
    code: str
    engine_cc: int
    #: New-car OTR in IDR at BASE_OTR_YEAR price level.
    base_otr: int
    #: Trim desirability. Multiplies the residual ratio - a high trim holds
    #: value slightly better, an entry trim slightly worse.
    residual_modifier: float = 1.0


@dataclass(frozen=True)
class GenerationSpec:
    name: str
    year_start: int
    year_end: int | None
    variants: list[VariantSpec]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    body_type: str
    segment: str
    fuel_type: str
    #: Share of this brand's volume. Normalised within the brand.
    share: float
    #: Annual depreciation constant. Higher = faster value loss. MPVs with
    #: strong secondary demand sit low; premium and niche models sit high.
    depreciation_k: float
    generations: list[GenerationSpec] = field(default_factory=list)


@dataclass(frozen=True)
class BrandSpec:
    name: str
    wmi: str
    country: str
    models: list[ModelSpec]


def _gen(name: str, y0: int, y1: int | None, variants: list[VariantSpec]) -> GenerationSpec:
    return GenerationSpec(name=name, year_start=y0, year_end=y1, variants=variants)


CATALOG: list[BrandSpec] = [
    BrandSpec(
        name="Toyota",
        wmi="MHF",
        country="ID",
        models=[
            ModelSpec(
                name="Avanza", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.30, depreciation_k=0.118,
                generations=[
                    _gen("W100 (2011-2021)", 2011, 2021, [
                        VariantSpec("E", "MT", "F651RM-GMMFJJ", 1329, 189_000_000, 0.97),
                        VariantSpec("E", "AT", "F651RM-GMQFJJ", 1329, 202_000_000, 0.98),
                        VariantSpec("G", "MT", "F653RM-GMMFJJ", 1496, 215_000_000, 1.00),
                        VariantSpec("G", "AT", "F653RM-GMQFJJ", 1496, 229_000_000, 1.02),
                        VariantSpec("Veloz", "AT", "F654RM-GMQFJJ", 1496, 248_000_000, 1.04),
                    ]),
                    _gen("W101 (2021-)", 2021, None, [
                        VariantSpec("E", "MT", "W101RE-GMMFJJ", 1329, 234_000_000, 0.98),
                        VariantSpec("G", "CVT", "W101RE-GMCFJJ", 1496, 268_000_000, 1.02),
                        VariantSpec("Veloz Q", "CVT", "W101RV-GMCFJJ", 1496, 298_000_000, 1.05),
                    ]),
                ],
            ),
            ModelSpec(
                name="Innova", body_type="mpv", segment="medium_mpv", fuel_type="solar",
                share=0.22, depreciation_k=0.101,
                generations=[
                    _gen("AN140 Reborn (2015-2022)", 2015, 2022, [
                        VariantSpec("G", "MT", "AN144R-NHMSKD", 2393, 372_000_000, 1.00),
                        VariantSpec("G", "AT", "AN144R-NHASKD", 2393, 392_000_000, 1.02),
                        VariantSpec("V", "AT", "AN144R-NHASKV", 2393, 448_000_000, 1.04),
                        VariantSpec("Venturer", "AT", "AN144R-NHASKW", 2393, 476_000_000, 1.05),
                    ]),
                    _gen("AN160 Zenix (2022-)", 2022, None, [
                        VariantSpec("G", "CVT", "AN160Z-GMCFJJ", 1987, 458_000_000, 1.01),
                        VariantSpec("V HV", "CVT", "AN160Z-HVCFJJ", 1987, 558_000_000, 1.03),
                    ]),
                ],
            ),
            ModelSpec(
                name="Rush", body_type="suv", segment="low_suv", fuel_type="bensin",
                share=0.14, depreciation_k=0.115,
                generations=[
                    _gen("F800 (2017-)", 2017, None, [
                        VariantSpec("G", "MT", "F800RE-GMMFJJ", 1496, 261_000_000, 0.99),
                        VariantSpec("G", "AT", "F800RE-GMQFJJ", 1496, 273_000_000, 1.01),
                        VariantSpec("TRD Sportivo", "AT", "F800RE-GMQFJT", 1496, 288_000_000, 1.03),
                    ]),
                ],
            ),
            ModelSpec(
                name="Agya", body_type="hatchback", segment="lcgc", fuel_type="bensin",
                share=0.12, depreciation_k=0.141,
                generations=[
                    _gen("B100 (2013-2023)", 2013, 2023, [
                        VariantSpec("E", "MT", "B100RA-GMMFJJ", 998, 143_000_000, 0.95),
                        VariantSpec("G", "MT", "B101RA-GMMFJJ", 1197, 159_000_000, 0.98),
                        VariantSpec("G", "AT", "B101RA-GMQFJJ", 1197, 173_000_000, 1.00),
                    ]),
                ],
            ),
            ModelSpec(
                name="Calya", body_type="mpv", segment="lcgc", fuel_type="bensin",
                share=0.10, depreciation_k=0.133,
                generations=[
                    _gen("B400 (2016-)", 2016, None, [
                        VariantSpec("E", "MT", "B402RA-GMMFJJ", 1197, 160_000_000, 0.96),
                        VariantSpec("G", "MT", "B403RA-GMMFJJ", 1197, 172_000_000, 0.99),
                        VariantSpec("G", "AT", "B403RA-GMQFJJ", 1197, 186_000_000, 1.01),
                    ]),
                ],
            ),
            ModelSpec(
                name="Fortuner", body_type="suv", segment="medium_suv", fuel_type="solar",
                share=0.08, depreciation_k=0.109,
                generations=[
                    _gen("AN160 (2015-)", 2015, None, [
                        VariantSpec("4x2 G", "AT", "AN160F-GMQSKD", 2393, 568_000_000, 1.00),
                        VariantSpec("4x2 VRZ", "AT", "AN160F-VRQSKD", 2393, 642_000_000, 1.03),
                        VariantSpec("4x4 VRZ", "AT", "AN160F-VRQSK4", 2755, 728_000_000, 1.04),
                    ]),
                ],
            ),
            ModelSpec(
                name="Yaris", body_type="hatchback", segment="hatchback", fuel_type="bensin",
                share=0.04, depreciation_k=0.129,
                generations=[
                    _gen("XP150 (2014-2022)", 2014, 2022, [
                        VariantSpec("E", "MT", "NSP150R-EMMFJJ", 1496, 251_000_000, 0.97),
                        VariantSpec("G", "CVT", "NSP150R-GMCFJJ", 1496, 278_000_000, 1.00),
                        VariantSpec("TRD Sportivo", "CVT", "NSP150R-TMCFJJ", 1496, 296_000_000, 1.02),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Daihatsu",
        wmi="MHK",
        country="ID",
        models=[
            ModelSpec(
                name="Xenia", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.26, depreciation_k=0.127,
                generations=[
                    _gen("F650 (2011-2021)", 2011, 2021, [
                        VariantSpec("M", "MT", "F651RV-GMDFJJ", 1329, 176_000_000, 0.96),
                        VariantSpec("R", "MT", "F653RV-GMDFJJ", 1496, 196_000_000, 0.99),
                        VariantSpec("R", "AT", "F653RV-GMQFJJ", 1496, 210_000_000, 1.00),
                    ]),
                    _gen("W100 (2021-)", 2021, None, [
                        VariantSpec("M", "MT", "W100RV-GMDFJJ", 1329, 219_000_000, 0.97),
                        VariantSpec("R ADS", "CVT", "W100RV-GMCFJA", 1496, 271_000_000, 1.01),
                    ]),
                ],
            ),
            ModelSpec(
                name="Terios", body_type="suv", segment="low_suv", fuel_type="bensin",
                share=0.20, depreciation_k=0.121,
                generations=[
                    _gen("F800 (2017-)", 2017, None, [
                        VariantSpec("X", "MT", "F800RG-GMDFJJ", 1496, 238_000_000, 0.98),
                        VariantSpec("R", "AT", "F800RG-GMQFJJ", 1496, 268_000_000, 1.01),
                        VariantSpec("R ADS", "AT", "F800RG-GMQFJA", 1496, 283_000_000, 1.02),
                    ]),
                ],
            ),
            ModelSpec(
                name="Gran Max", body_type="van", segment="commercial", fuel_type="bensin",
                share=0.21, depreciation_k=0.147,
                generations=[
                    _gen("S400 (2007-)", 2007, None, [
                        VariantSpec("Blind Van", "MT", "S401RP-BMDFJJ", 1496, 158_000_000, 0.93),
                        VariantSpec("Pick Up 1.5", "MT", "S401RP-PMDFJJ", 1496, 164_000_000, 0.95),
                        VariantSpec("Minibus 1.5", "MT", "S402RP-MMDFJJ", 1496, 189_000_000, 0.97),
                    ]),
                ],
            ),
            ModelSpec(
                name="Ayla", body_type="hatchback", segment="lcgc", fuel_type="bensin",
                share=0.17, depreciation_k=0.148,
                generations=[
                    _gen("B100 (2013-2023)", 2013, 2023, [
                        VariantSpec("D", "MT", "B100RS-GMDFJJ", 998, 128_000_000, 0.93),
                        VariantSpec("X", "MT", "B101RS-GMDFJJ", 1197, 148_000_000, 0.97),
                        VariantSpec("R", "AT", "B101RS-GMQFJJ", 1197, 166_000_000, 0.99),
                    ]),
                ],
            ),
            ModelSpec(
                name="Sigra", body_type="mpv", segment="lcgc", fuel_type="bensin",
                share=0.16, depreciation_k=0.138,
                generations=[
                    _gen("B400 (2016-)", 2016, None, [
                        VariantSpec("D", "MT", "B400RS-GMDFJJ", 998, 139_000_000, 0.94),
                        VariantSpec("R", "MT", "B403RS-GMDFJJ", 1197, 163_000_000, 0.98),
                        VariantSpec("R", "AT", "B403RS-GMQFJJ", 1197, 178_000_000, 1.00),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Honda",
        wmi="MHR",
        country="ID",
        models=[
            ModelSpec(
                name="Brio", body_type="hatchback", segment="lcgc", fuel_type="bensin",
                share=0.31, depreciation_k=0.116,
                generations=[
                    _gen("DD1 (2018-)", 2018, None, [
                        VariantSpec("Satya S", "MT", "DD1-S-MT", 1199, 167_000_000, 0.97),
                        VariantSpec("Satya E", "CVT", "DD1-E-CVT", 1199, 191_000_000, 1.00),
                        VariantSpec("RS", "CVT", "DD1-RS-CVT", 1199, 246_000_000, 1.03),
                    ]),
                ],
            ),
            ModelSpec(
                name="Mobilio", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.19, depreciation_k=0.136,
                generations=[
                    _gen("DD4 (2014-2021)", 2014, 2021, [
                        VariantSpec("S", "MT", "DD4-S-MT", 1497, 208_000_000, 0.96),
                        VariantSpec("E", "CVT", "DD4-E-CVT", 1497, 243_000_000, 1.00),
                        VariantSpec("RS", "CVT", "DD4-RS-CVT", 1497, 268_000_000, 1.02),
                    ]),
                ],
            ),
            ModelSpec(
                name="HR-V", body_type="suv", segment="compact_suv", fuel_type="bensin",
                share=0.24, depreciation_k=0.112,
                generations=[
                    _gen("RU (2015-2021)", 2015, 2021, [
                        VariantSpec("S", "CVT", "RU1-S-CVT", 1497, 298_000_000, 0.99),
                        VariantSpec("E", "CVT", "RU1-E-CVT", 1497, 336_000_000, 1.01),
                        VariantSpec("Prestige", "CVT", "RU5-P-CVT", 1798, 396_000_000, 1.03),
                    ]),
                    _gen("RV (2022-)", 2022, None, [
                        VariantSpec("E", "CVT", "RV3-E-CVT", 1498, 389_000_000, 1.01),
                        VariantSpec("RS Turbo", "CVT", "RV5-RS-CVT", 1498, 476_000_000, 1.04),
                    ]),
                ],
            ),
            ModelSpec(
                name="Jazz", body_type="hatchback", segment="hatchback", fuel_type="bensin",
                share=0.14, depreciation_k=0.104,
                generations=[
                    _gen("GK5 (2014-2021)", 2014, 2021, [
                        VariantSpec("S", "MT", "GK5-S-MT", 1497, 253_000_000, 0.99),
                        VariantSpec("RS", "CVT", "GK5-RS-CVT", 1497, 298_000_000, 1.04),
                    ]),
                ],
            ),
            ModelSpec(
                name="CR-V", body_type="suv", segment="medium_suv", fuel_type="bensin",
                share=0.12, depreciation_k=0.118,
                generations=[
                    _gen("RW (2017-2023)", 2017, 2023, [
                        VariantSpec("2.0", "CVT", "RW1-20-CVT", 1997, 498_000_000, 0.99),
                        VariantSpec("1.5 Turbo Prestige", "CVT", "RW2-15T-CVT", 1498, 578_000_000, 1.02),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Mitsubishi",
        wmi="MHM",
        country="ID",
        models=[
            ModelSpec(
                name="Xpander", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.52, depreciation_k=0.109,
                generations=[
                    _gen("A1 (2017-)", 2017, None, [
                        VariantSpec("GLS", "MT", "A1G-GLS-MT", 1499, 248_000_000, 0.98),
                        VariantSpec("Exceed", "AT", "A1G-EXC-AT", 1499, 273_000_000, 1.00),
                        VariantSpec("Ultimate", "AT", "A1G-ULT-AT", 1499, 306_000_000, 1.03),
                        VariantSpec("Cross Premium", "AT", "A1X-CRP-AT", 1499, 336_000_000, 1.04),
                    ]),
                ],
            ),
            ModelSpec(
                name="Pajero Sport", body_type="suv", segment="medium_suv", fuel_type="solar",
                share=0.26, depreciation_k=0.114,
                generations=[
                    _gen("QF (2016-)", 2016, None, [
                        VariantSpec("Exceed 4x2", "AT", "QF-EXC-4X2", 2442, 566_000_000, 0.99),
                        VariantSpec("Dakar 4x2", "AT", "QF-DKR-4X2", 2442, 668_000_000, 1.02),
                        VariantSpec("Dakar Ultimate 4x4", "AT", "QF-DKU-4X4", 2442, 752_000_000, 1.03),
                    ]),
                ],
            ),
            ModelSpec(
                name="L300", body_type="pickup", segment="commercial", fuel_type="solar",
                share=0.22, depreciation_k=0.131,
                generations=[
                    _gen("L300 (1981-)", 1981, None, [
                        VariantSpec("Pick Up", "MT", "L300-PU-MT", 2477, 248_000_000, 0.96),
                        VariantSpec("Box", "MT", "L300-BX-MT", 2477, 268_000_000, 0.95),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Suzuki",
        wmi="MHY",
        country="ID",
        models=[
            ModelSpec(
                name="Ertiga", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.38, depreciation_k=0.131,
                generations=[
                    _gen("YHA (2018-)", 2018, None, [
                        VariantSpec("GA", "MT", "YHA-GA-MT", 1462, 213_000_000, 0.95),
                        VariantSpec("GL", "MT", "YHA-GL-MT", 1462, 238_000_000, 0.98),
                        VariantSpec("GX", "AT", "YHA-GX-AT", 1462, 268_000_000, 1.00),
                        VariantSpec("Sport", "AT", "YHA-SP-AT", 1462, 286_000_000, 1.01),
                    ]),
                ],
            ),
            ModelSpec(
                name="Carry", body_type="pickup", segment="commercial", fuel_type="bensin",
                share=0.34, depreciation_k=0.139,
                generations=[
                    _gen("Carry Pick Up (2019-)", 2019, None, [
                        VariantSpec("Flat Deck", "MT", "CRY-FD-MT", 1462, 158_000_000, 0.94),
                        VariantSpec("Wide Deck", "MT", "CRY-WD-MT", 1462, 166_000_000, 0.95),
                    ]),
                ],
            ),
            ModelSpec(
                name="XL7", body_type="suv", segment="low_suv", fuel_type="bensin",
                share=0.28, depreciation_k=0.128,
                generations=[
                    _gen("XL7 (2020-)", 2020, None, [
                        VariantSpec("Zeta", "MT", "XL7-ZT-MT", 1462, 238_000_000, 0.97),
                        VariantSpec("Beta", "AT", "XL7-BT-AT", 1462, 268_000_000, 1.00),
                        VariantSpec("Alpha", "AT", "XL7-AL-AT", 1462, 286_000_000, 1.01),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Nissan",
        wmi="JN1",
        country="JP",
        models=[
            ModelSpec(
                name="Livina", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.62, depreciation_k=0.152,
                generations=[
                    _gen("L11 (2019-)", 2019, None, [
                        VariantSpec("EL", "MT", "L11-EL-MT", 1499, 236_000_000, 0.93),
                        VariantSpec("VL", "AT", "L11-VL-AT", 1499, 278_000_000, 0.96),
                    ]),
                ],
            ),
            ModelSpec(
                name="Serena", body_type="mpv", segment="medium_mpv", fuel_type="bensin",
                share=0.38, depreciation_k=0.163,
                generations=[
                    _gen("C27 (2019-)", 2019, None, [
                        VariantSpec("Highway Star", "CVT", "C27-HWS-CVT", 1997, 488_000_000, 0.92),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Wuling",
        wmi="MJB",
        country="ID",
        models=[
            ModelSpec(
                name="Confero", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.45, depreciation_k=0.178,
                generations=[
                    _gen("Confero (2017-)", 2017, None, [
                        VariantSpec("S", "MT", "CNF-S-MT", 1485, 168_000_000, 0.86),
                        VariantSpec("S ACT", "MT", "CNF-SACT-MT", 1485, 198_000_000, 0.88),
                    ]),
                ],
            ),
            ModelSpec(
                name="Almaz", body_type="suv", segment="compact_suv", fuel_type="bensin",
                share=0.55, depreciation_k=0.184,
                generations=[
                    _gen("Almaz (2019-)", 2019, None, [
                        VariantSpec("Exclusive", "CVT", "ALM-EX-CVT", 1451, 338_000_000, 0.85),
                        VariantSpec("RS Pro", "CVT", "ALM-RS-CVT", 1451, 408_000_000, 0.87),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Isuzu",
        wmi="MHL",
        country="ID",
        models=[
            ModelSpec(
                name="Panther", body_type="mpv", segment="medium_mpv", fuel_type="solar",
                share=0.42, depreciation_k=0.094,
                generations=[
                    _gen("Panther (2000-2021)", 2000, 2021, [
                        VariantSpec("LS Turbo", "MT", "PTH-LS-MT", 2499, 378_000_000, 1.02),
                        VariantSpec("Grand Touring", "MT", "PTH-GT-MT", 2499, 398_000_000, 1.03),
                    ]),
                ],
            ),
            ModelSpec(
                name="D-Max", body_type="pickup", segment="commercial", fuel_type="solar",
                share=0.58, depreciation_k=0.121,
                generations=[
                    _gen("RT85 (2015-)", 2015, None, [
                        VariantSpec("Single Cab", "MT", "RT85-SC-MT", 2499, 328_000_000, 0.98),
                        VariantSpec("Double Cab 4x4", "MT", "RT85-DC4-MT", 2999, 496_000_000, 1.00),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Hyundai",
        wmi="MJE",
        country="ID",
        models=[
            ModelSpec(
                name="Creta", body_type="suv", segment="compact_suv", fuel_type="bensin",
                share=0.56, depreciation_k=0.158,
                generations=[
                    _gen("SU2 (2022-)", 2022, None, [
                        VariantSpec("Active", "MT", "SU2-AC-MT", 1497, 288_000_000, 0.90),
                        VariantSpec("Style", "CVT", "SU2-ST-CVT", 1497, 348_000_000, 0.92),
                        VariantSpec("Prime", "CVT", "SU2-PR-CVT", 1497, 408_000_000, 0.93),
                    ]),
                ],
            ),
            ModelSpec(
                name="Stargazer", body_type="mpv", segment="low_mpv", fuel_type="bensin",
                share=0.44, depreciation_k=0.166,
                generations=[
                    _gen("KS (2022-)", 2022, None, [
                        VariantSpec("Active", "MT", "KS-AC-MT", 1497, 248_000_000, 0.89),
                        VariantSpec("Style", "CVT", "KS-ST-CVT", 1497, 298_000_000, 0.91),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Mazda",
        wmi="JM1",
        country="JP",
        models=[
            ModelSpec(
                name="CX-5", body_type="suv", segment="medium_suv", fuel_type="bensin",
                share=1.0, depreciation_k=0.149,
                generations=[
                    _gen("KF (2017-)", 2017, None, [
                        VariantSpec("Elite", "AT", "KF-EL-AT", 2488, 588_000_000, 0.94),
                        VariantSpec("Kuro", "AT", "KF-KR-AT", 2488, 638_000_000, 0.95),
                    ]),
                ],
            ),
        ],
    ),
    BrandSpec(
        name="Kia",
        wmi="KNA",
        country="KR",
        models=[
            ModelSpec(
                name="Seltos", body_type="suv", segment="compact_suv", fuel_type="bensin",
                share=1.0, depreciation_k=0.172,
                generations=[
                    _gen("SP2 (2019-2023)", 2019, 2023, [
                        VariantSpec("EX", "CVT", "SP2-EX-CVT", 1497, 358_000_000, 0.88),
                    ]),
                ],
            ),
        ],
    ),
]


def iter_variants():
    """Yield (brand, model, generation, variant) for every catalog leaf."""
    for brand in CATALOG:
        for model in brand.models:
            for generation in model.generations:
                for variant in generation.variants:
                    yield brand, model, generation, variant


def variant_count() -> int:
    return sum(1 for _ in iter_variants())
