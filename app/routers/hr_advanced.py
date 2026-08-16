"""API RH enterprise — départements, contrats, primes, recrutement, évaluations, analytics."""
from __future__ import annotations

from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api_guards import require_action
from app.database import get_db
from app.models import User
from app.models_erp import Employee, LeaveRequest
from app.models_enterprise_ops import (
    HrBonus, HrContract, HrDepartment, HrEvaluation, HrRecruitment, HrTrainingPlan,
)
from app.models_accounting import PayrollRun
from app import schemas_enterprise_ops as se
from app.services.hr_pdf_service import render_employee_pdf, render_hr_report_pdf

router = APIRouter(prefix="/api/erp/hr", tags=["hr-advanced"])


def _crud_list(model, db: Session, order_by=None):
    q = db.query(model)
    if order_by is not None:
        q = q.order_by(order_by)
    return q.all()


def _crud_get(model, pk: int, db: Session):
    obj = db.query(model).filter(model.id == pk).first()
    if not obj:
        raise HTTPException(404)
    return obj


def _crud_create(model, data, db: Session):
    obj = model(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _crud_update(model, pk: int, data, db: Session):
    obj = _crud_get(model, pk, db)
    for k, v in data.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


def _crud_delete(model, pk: int, db: Session):
    obj = _crud_get(model, pk, db)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/analytics")
def hr_analytics(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    employees = db.query(Employee).all()
    active = [e for e in employees if (e.status or "") == "actif"]
    depts = Counter((e.department or "Non affecté").strip() or "Non affecté" for e in active)
    positions = Counter((e.position or "—").strip() or "—" for e in active)
    gender = Counter(getattr(e, "gender", None) or "non renseigné" for e in active)
    contracts = Counter(getattr(e, "contract_type", None) or "CDI" for e in active)
    leaves = db.query(LeaveRequest).all()
    approved = [l for l in leaves if (l.status or "") == "approuvé"]
    absent_rate = round(len(approved) / max(len(active), 1) * 100, 1)
    runs = db.query(PayrollRun).order_by(PayrollRun.period_year, PayrollRun.period_month).limit(12).all()
    payroll_evolution = [
        {"label": f"{r.period_month:02d}/{r.period_year}", "gross": r.total_gross, "net": r.total_net, "charges": r.total_charges}
        for r in runs
    ]
    salary_buckets = {"0-200k": 0, "200-500k": 0, "500k-1M": 0, "1M+": 0}
    for e in active:
        s = float(e.salary_base or 0)
        if s < 200_000:
            salary_buckets["0-200k"] += 1
        elif s < 500_000:
            salary_buckets["200-500k"] += 1
        elif s < 1_000_000:
            salary_buckets["500k-1M"] += 1
        else:
            salary_buckets["1M+"] += 1
    org = []
    for d in db.query(HrDepartment).filter(HrDepartment.status == "actif").all():
        org.append({
            "id": d.id, "name": d.name, "parent_id": d.parent_id,
            "manager": d.manager_name, "count": depts.get(d.name, 0),
        })
    if not org:
        org = [{"id": i, "name": k, "parent_id": None, "manager": "", "count": v} for i, (k, v) in enumerate(depts.most_common(8))]
    return {
        "headcount": len(employees),
        "active_count": len(active),
        "masse_salariale": round(sum(float(e.salary_base or 0) for e in active), 2),
        "pending_leaves": len([l for l in leaves if (l.status or "") == "en attente"]),
        "absenteeism_rate": absent_rate,
        "presence_rate": round(100 - min(absent_rate, 100), 1),
        "departments_chart": {"labels": [x[0] for x in depts.most_common(10)], "values": [x[1] for x in depts.most_common(10)]},
        "positions_chart": {"labels": [x[0] for x in positions.most_common(8)], "values": [x[1] for x in positions.most_common(8)]},
        "gender_chart": {"labels": list(gender.keys()), "values": list(gender.values())},
        "contracts_chart": {"labels": list(contracts.keys()), "values": list(contracts.values())},
        "salary_distribution": {"labels": list(salary_buckets.keys()), "values": list(salary_buckets.values())},
        "payroll_evolution": payroll_evolution,
        "org_tree": org,
        "recruitments_open": db.query(HrRecruitment).filter(HrRecruitment.status == "ouvert").count(),
        "evaluations_pending": db.query(HrEvaluation).filter(HrEvaluation.status == "brouillon").count(),
    }


@router.get("/employees/{eid}/pdf")
def employee_pdf(eid: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    emp = db.query(Employee).filter(Employee.id == eid).first()
    if not emp:
        raise HTTPException(404)
    pdf = render_employee_pdf(emp, db)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="fiche-{emp.matricule}.pdf"'})


@router.get("/report/pdf")
def hr_report_pdf(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    pdf = render_hr_report_pdf(db)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="rapport-rh.pdf"'})


# ——— Départements ———
@router.get("/departments", response_model=List[se.HrDepartmentOut])
def list_departments(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrDepartment, db, HrDepartment.name)


@router.post("/departments", response_model=se.HrDepartmentOut)
def create_department(data: se.HrDepartmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrDepartment, data, db)


@router.put("/departments/{pk}", response_model=se.HrDepartmentOut)
def update_department(pk: int, data: se.HrDepartmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrDepartment, pk, data, db)


@router.delete("/departments/{pk}")
def delete_department(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrDepartment, pk, db)


# ——— Contrats ———
@router.get("/contracts", response_model=List[se.HrContractOut])
def list_contracts(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrContract, db, HrContract.id.desc())


@router.post("/contracts", response_model=se.HrContractOut)
def create_contract(data: se.HrContractIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrContract, data, db)


@router.put("/contracts/{pk}", response_model=se.HrContractOut)
def update_contract(pk: int, data: se.HrContractIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrContract, pk, data, db)


@router.delete("/contracts/{pk}")
def delete_contract(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrContract, pk, db)


# ——— Primes ———
@router.get("/bonuses", response_model=List[se.HrBonusOut])
def list_bonuses(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrBonus, db, HrBonus.id.desc())


@router.post("/bonuses", response_model=se.HrBonusOut)
def create_bonus(data: se.HrBonusIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrBonus, data, db)


@router.put("/bonuses/{pk}", response_model=se.HrBonusOut)
def update_bonus(pk: int, data: se.HrBonusIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrBonus, pk, data, db)


@router.delete("/bonuses/{pk}")
def delete_bonus(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrBonus, pk, db)


# ——— Recrutements ———
@router.get("/recruitments", response_model=List[se.HrRecruitmentOut])
def list_recruitments(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrRecruitment, db, HrRecruitment.id.desc())


@router.post("/recruitments", response_model=se.HrRecruitmentOut)
def create_recruitment(data: se.HrRecruitmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrRecruitment, data, db)


@router.put("/recruitments/{pk}", response_model=se.HrRecruitmentOut)
def update_recruitment(pk: int, data: se.HrRecruitmentIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrRecruitment, pk, data, db)


@router.delete("/recruitments/{pk}")
def delete_recruitment(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrRecruitment, pk, db)


# ——— Évaluations ———
@router.get("/evaluations", response_model=List[se.HrEvaluationOut])
def list_evaluations(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrEvaluation, db, HrEvaluation.id.desc())


@router.post("/evaluations", response_model=se.HrEvaluationOut)
def create_evaluation(data: se.HrEvaluationIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrEvaluation, data, db)


@router.put("/evaluations/{pk}", response_model=se.HrEvaluationOut)
def update_evaluation(pk: int, data: se.HrEvaluationIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrEvaluation, pk, data, db)


@router.delete("/evaluations/{pk}")
def delete_evaluation(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrEvaluation, pk, db)


# ——— Formations planifiées ———
@router.get("/training-plans", response_model=List[se.HrTrainingPlanOut])
def list_training_plans(db: Session = Depends(get_db), _: User = Depends(require_action("hr", "view"))):
    return _crud_list(HrTrainingPlan, db, HrTrainingPlan.start_date.desc())


@router.post("/training-plans", response_model=se.HrTrainingPlanOut)
def create_training_plan(data: se.HrTrainingPlanIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "create"))):
    return _crud_create(HrTrainingPlan, data, db)


@router.put("/training-plans/{pk}", response_model=se.HrTrainingPlanOut)
def update_training_plan(pk: int, data: se.HrTrainingPlanIn, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "update"))):
    return _crud_update(HrTrainingPlan, pk, data, db)


@router.delete("/training-plans/{pk}")
def delete_training_plan(pk: int, db: Session = Depends(get_db), _: User = Depends(require_action("hr", "delete"))):
    return _crud_delete(HrTrainingPlan, pk, db)
