# main.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
import pdfplumber
import io
import re
from datetime import datetime


app = FastAPI()

# allow frontend dev server
origins = [
    "http://localhost:5173",  # Vite default
    "http://localhost:3000",
    "https://loandoccopilot-frontend.vercel.app/"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class FieldChange(BaseModel):
    field: str
    from_value: str
    to_value: str
    impact: str

class ESGCheckResult(BaseModel):
    rule_name: str
    passed: bool
    comment: str

class AnalyzeResponse(BaseModel):
    key_terms_v1: Dict[str, Any]
    key_terms_v2: Dict[str, Any]
    changes: List[FieldChange]
    esg_checks: List[ESGCheckResult]

def extract_text_from_pdf(file_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return text

def find_first(pattern: str, text: str, flags=re.IGNORECASE):
    """
    Find the first match of a regex pattern and return group 1.
    If nothing is found, return None.
    """
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def contains_any(text: str, keywords):
    """
    Check if any of the keywords exists in the text (case-insensitive).
    """
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)

def extract_key_terms(text: str) -> Dict[str, Any]:
    """
    Extract key terms from our demo facility agreement PDFs.
    This is tailored to our own sample wording (Facility Amount:, etc.).
    """

    # Facility Amount: EUR 150,000,000
    facility_amount = find_first(
        r"Facility Amount:\s*([A-Z]{3}\s[0-9,\,\.]+)",
        text,
    )

    # Interest Margin: 2.50% per annum
    margin = find_first(
        r"Interest Margin:\s*([0-9\.]+\s*%\s*per annum)",
        text,
    )

    # Maturity Date: 31 March 2028
    maturity = find_first(
        r"Maturity Date:\s*([0-9]{1,2}\s+\w+\s+[0-9]{4})",
        text,
    )

    # Borrower: GreenTech Energy Ltd.
    borrower = find_first(
        r"Borrower:\s*(.+)",
        text,
    )

    # Purpose: The Facility will be used...
    purpose = find_first(
        r"Purpose:\s*(.+)",
        text,
    )

    return {
        "facility_amount": facility_amount or "Not detected",
        "margin": margin or "Not detected",
        "maturity_date": maturity or "Not detected",
        "borrower": borrower or "Not detected",
        "purpose": purpose or "Not detected",
    }



def compare_terms(v1: Dict[str, Any], v2: Dict[str, Any]) -> List[FieldChange]:
    """
    Compare extracted key terms between Version 1 and Version 2.
    Adds simple 'impact' descriptions by field.
    """
    changes: List[FieldChange] = []

    for field in v1.keys():
        old_val = v1.get(field)
        new_val = v2.get(field)

        if old_val == new_val:
            continue

        # Default impact message
        impact = "Change detected"

        if field == "margin":
            impact = "Economic impact: margin changed (cost of debt)."
        elif field == "facility_amount":
            impact = "Economic impact: facility size changed."
        elif field == "maturity_date":
            impact = "Term/risk impact: maturity changed."
        elif field == "borrower":
            impact = "Counterparty details changed."
        elif field == "purpose":
            impact = "Use of proceeds changed."

        changes.append(
            FieldChange(
                field=field,
                from_value=str(old_val),
                to_value=str(new_val),
                impact=impact,
            )
        )

    return changes


def run_esg_checks(text: str) -> List[ESGCheckResult]:
    """
    Very simple 'Greener Lending' checks based on keyword searches.
    Not legally accurate, but great for a demo.
    """

    checks: List[ESGCheckResult] = []

    # 1. Use of proceeds clearly defined
    checks.append(
        ESGCheckResult(
            rule_name="Use of proceeds clearly defined",
            passed=contains_any(
                text,
                [
                    "use of proceeds",
                    "proceeds of the facility",
                    "shall be applied towards",
                ],
            ),
            comment="Green loans should clearly define how proceeds will be used.",
        )
    )

    # 2. Environmental / sustainability objectives described
    checks.append(
        ESGCheckResult(
            rule_name="Environmental / sustainability objectives described",
            passed=contains_any(
                text,
                [
                    "green project",
                    "sustainability objective",
                    "environmental objective",
                    "renewable energy",
                    "energy efficiency",
                    "climate",
                ],
            ),
            comment="Looks for language around green or sustainability objectives.",
        )
    )

    # 3. KPIs or performance targets
    checks.append(
        ESGCheckResult(
            rule_name="KPIs or performance targets included",
            passed=contains_any(
                text,
                [
                    "key performance indicator",
                    "kpi",
                    "sustainability performance target",
                    "performance target",
                ],
            ),
            comment="Searches for sustainability-linked KPIs or performance targets.",
        )
    )

    # 4. Reporting obligations
    checks.append(
        ESGCheckResult(
            rule_name="Ongoing reporting obligations present",
            passed=contains_any(
                text,
                [
                    "reporting",
                    "annual report",
                    "sustainability report",
                    "periodic report",
                ],
            ),
            comment="Checks if the borrower is required to report on performance.",
        )
    )

    # 5. External review / verification
    checks.append(
        ESGCheckResult(
            rule_name="External review / verification mentioned",
            passed=contains_any(
                text,
                [
                    "second party opinion",
                    "external review",
                    "external verifier",
                    "assurance provider",
                ],
            ),
            comment="Looks for external ESG review or verification requirements.",
        )
    )

    return checks


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_docs(
    doc_v1: UploadFile = File(...),
    doc_v2: UploadFile = File(...),
):
    v1_bytes = await doc_v1.read()
    v2_bytes = await doc_v2.read()

    # TODO: add docx handling; for now assume PDFs
    text_v1 = extract_text_from_pdf(v1_bytes)
    text_v2 = extract_text_from_pdf(v2_bytes)

    key_terms_v1 = extract_key_terms(text_v1)
    key_terms_v2 = extract_key_terms(text_v2)

    changes = compare_terms(key_terms_v1, key_terms_v2)

    # run ESG on the latest version
    esg_checks = run_esg_checks(text_v2)

    return AnalyzeResponse(
        key_terms_v1=key_terms_v1,
        key_terms_v2=key_terms_v2,
        changes=changes,
        esg_checks=esg_checks
    )
