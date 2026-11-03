from datetime import date

from fastapi.templating import Jinja2Templates

from .config import APP_DIR
from .models import DASHBOARD_ORDER, STATUS_LABELS, ProjectStatus

templates = Jinja2Templates(directory=APP_DIR / "templates")


def _nice_date(value: date | None) -> str:
    if not value:
        return ""
    return value.strftime("%b %d, %Y").replace(" 0", " ")


templates.env.filters["nice_date"] = _nice_date
templates.env.globals.update(
    STATUS_LABELS=STATUS_LABELS,
    STATUSES=list(ProjectStatus),
    DASHBOARD_ORDER=DASHBOARD_ORDER,
    HOOK_SIZES=[
        "2.25 mm (B-1)", "2.75 mm (C-2)", "3.25 mm (D-3)", "3.5 mm (E-4)", "3.75 mm (F-5)",
        "4.0 mm (G-6)", "4.5 mm (7)", "5.0 mm (H-8)", "5.5 mm (I-9)", "6.0 mm (J-10)",
        "6.5 mm (K-10.5)", "8.0 mm (L-11)", "9.0 mm (M/N-13)", "10.0 mm (N/P-15)",
        "12.0 mm (O-17)", "15.0 mm (P/Q)",
    ],
)
