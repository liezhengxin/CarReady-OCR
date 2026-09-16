"""Caready ML: pricing models, grading engine, provider interfaces.

Milestone map:

    M2  ocr/         OCR provider implementations (stub, paddle, cloud_docai)
        crosschecks/ typed cross-check rules
    M4  catalog/     variant matcher
    M5  pricing/     residual anchor, LightGBM quantile models, baselines,
                     censoring, SHAP explanations
    M6  grading/     config-driven grade computation
        vision/      vision provider implementations

`providers.py` holds the interfaces now so the swap points exist before the
implementations do.
"""

__version__ = "0.1.0"
