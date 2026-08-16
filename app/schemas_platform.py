"""Schémas API plateforme enterprise."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schema_base import PeyaSchema


class ApprovalRuleIn(PeyaSchema):
    module: str
    min_amount: float = 0
    levels_json: str = '[{"role":"manager"},{"role":"admin"},{"role":"admin"}]'
    is_active: bool = True


class ApprovalRuleOut(ApprovalRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: Optional[int] = None


class ApprovalDecideIn(BaseModel):
    action: str = Field(description="approve | reject | revision")
    comment: str = ""


class ApprovalSubmitIn(BaseModel):
    module: str
    title: str
    amount: float = 0
    entity_type: str = ""
    entity_id: Optional[int] = None
    notes: str = ""


class NotificationRuleIn(PeyaSchema):
    event_type: str
    channels_json: str = '["in_app","email"]'
    is_active: bool = True
    template_title: str = ""
    template_body: str = ""


class NotificationRuleOut(NotificationRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PortalTokenIn(BaseModel):
    client_id: int
    days_valid: int = 90


class PortalTokenOut(BaseModel):
    token: str
    url: str
    expires_at: str


class SupportTicketIn(PeyaSchema):
    client_id: Optional[int] = None
    subject: str
    description: str = ""
    priority: str = "normale"


class SupportTicketOut(SupportTicketIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reference: str = ""
    status: str = "ouvert"
    opened_at: str = ""


class OfflineSyncItem(BaseModel):
    op: str
    entity: str
    payload: dict = {}


class OfflineSyncBatchIn(BaseModel):
    device_id: str = ""
    items: List[OfflineSyncItem] = []


class SearchResultOut(BaseModel):
    type: str
    id: int
    label: str
    view: str
    meta: str = ""
