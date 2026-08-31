import os
from datetime import date, datetime, time
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Date, Integer, String, Text, Time, and_, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookings.db")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")

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
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
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

def parse_time(value: str) -> time:
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

def verify_admin(x_admin_password: Optional[str]):
    if not x_admin_password or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверный пароль администратора")

@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/bookings")
def list_bookings(year: Optional[int] = None, month: Optional[int] = None):
    with SessionLocal() as db:
        stmt = select(Booking)
        if year and month:
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
        conflict = db.scalar(
            select(Booking).where(
                and_(
                    Booking.booking_date == payload.booking_date,
                    Booking.start_time < end,
                    Booking.end_time > start,
                )
            )
        )
        if conflict:
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
def delete_booking(booking_id: int, x_admin_password: Optional[str] = Header(default=None)):
    verify_admin(x_admin_password)
    with SessionLocal() as db:
        booking = db.get(Booking, booking_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        db.delete(booking)
        db.commit()
    return {"ok": True}
