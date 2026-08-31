
import os
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, Integer, Text, Date, Time, select, and_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookings.db")
# Render/older providers sometimes return postgres:// instead of postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    pass

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(200), default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[datetime.time] = mapped_column(Time)
    end_time: Mapped[datetime.time] = mapped_column(Time)
    sample_info: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat(timespec="seconds"))

Base.metadata.create_all(engine)

app = FastAPI(title="Confotec NR500 Booking")

class BookingIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    department: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=200)
    booking_date: date
    start_time: str
    end_time: str
    sample_info: str = Field(default="", max_length=1000)
    comment: str = Field(default="", max_length=2000)

def parse_time(value: str):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени")

def serialize(b: Booking):
    return {
        "id": b.id,
        "full_name": b.full_name,
        "department": b.department,
        "contact": b.contact,
        "booking_date": b.booking_date.isoformat(),
        "start_time": b.start_time.strftime("%H:%M"),
        "end_time": b.end_time.strftime("%H:%M"),
        "sample_info": b.sample_info,
        "comment": b.comment,
        "created_at": b.created_at,
    }

@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.get("/api/bookings")
def list_bookings(year: Optional[int] = None, month: Optional[int] = None):
    with SessionLocal() as db:
        stmt = select(Booking)
        if year and month:
            # portable month range
            if month == 12:
                start = date(year, 12, 1)
                end = date(year + 1, 1, 1)
            else:
                start = date(year, month, 1)
                end = date(year, month + 1, 1)
            stmt = stmt.where(and_(Booking.booking_date >= start, Booking.booking_date < end))
        stmt = stmt.order_by(Booking.booking_date, Booking.start_time)
        return [serialize(x) for x in db.scalars(stmt).all()]

@app.post("/api/bookings")
def create_booking(payload: BookingIn):
    start = parse_time(payload.start_time)
    end = parse_time(payload.end_time)
    if end <= start:
        raise HTTPException(status_code=400, detail="Время окончания должно быть позже времени начала")

    with SessionLocal() as db:
        overlaps = db.scalar(
            select(Booking).where(
                and_(
                    Booking.booking_date == payload.booking_date,
                    Booking.start_time < end,
                    Booking.end_time > start,
                )
            )
        )
        if overlaps:
            raise HTTPException(status_code=409, detail="Это время уже занято")

        booking = Booking(
            full_name=payload.full_name.strip(),
            department=payload.department.strip(),
            contact=payload.contact.strip(),
            booking_date=payload.booking_date,
            start_time=start,
            end_time=end,
            sample_info=payload.sample_info.strip(),
            comment=payload.comment.strip(),
        )
        db.add(booking)
        db.commit()
        db.refresh(booking)
        return serialize(booking)

@app.delete("/api/bookings/{booking_id}")
def delete_booking(booking_id: int):
    with SessionLocal() as db:
        b = db.get(Booking, booking_id)
        if not b:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        db.delete(b)
        db.commit()
    return {"ok": True}

@app.get("/api/health")
def health():
    return {"ok": True}
