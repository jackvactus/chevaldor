"""Événements calendrier personnalisés (rendez-vous, réunions, rappels)."""
from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, Text
from app.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    category = Column(String, default="admin")  # compta, ventes, achats, stock, rh, admin, direction
    event_type = Column(String, default="meeting")  # meeting, task, reminder, appointment...
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    start_time = Column(String, default="09:00")
    end_time = Column(String, default="10:00")
    all_day = Column(Boolean, default=True)
    priority = Column(String, default="normal")  # low, normal, high, critical
    owner = Column(String, default="")
    status = Column(String, default="planifié")  # planifié, en cours, terminé, annulé
    participants_json = Column(Text, default="[]")
    attachments_json = Column(Text, default="[]")
    comments_json = Column(Text, default="[]")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Date)
