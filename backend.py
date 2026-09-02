"""
Бэкенд для трекера отказа от вредных привычек (PostgreSQL + FastAPI + aiogram)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from bot import bot, dp

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = "sqlite+aiosqlite:///./quit_tracker.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class UserDB(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    habits = relationship("HabitDB", back_populates="user", cascade="all, delete-orphan")
    relapses = relationship("RelapseDB", back_populates="user", cascade="all, delete-orphan")


class HabitDB(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    type = Column(String, nullable=False)
    quit_date = Column(String, nullable=False)
    per_day = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    unit_size = Column(Float, nullable=False)

    user = relationship("UserDB", back_populates="habits")

    __table_args__ = (UniqueConstraint("user_id", "type", name="uix_user_habit"),)


class RelapseDB(Base):
    __tablename__ = "relapses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    habit_type = Column(String, nullable=False)
    relapse_date = Column(DateTime, default=datetime.utcnow)
    reason = Column(Text, nullable=True)

    user = relationship("UserDB", back_populates="relapses")


class FriendshipDB(Base):
    __tablename__ = "friendships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    friend_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uix_user_friend"),)


HabitType = Literal["vape", "alcohol"]


class HabitSchema(BaseModel):
    user_id: int
    type: HabitType
    quit_date: str
    per_day: float
    unit_price: float
    unit_size: float


class RelapseSchema(BaseModel):
    user_id: int
    habit_type: HabitType
    reason: Optional[str] = "Не указана"


class AddFriendSchema(BaseModel):
    user_id: int
    friend_id: int


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    polling_task = asyncio.create_task(dp.start_polling(bot))
    yield
    polling_task.cancel()
    await bot.session.close()


app = FastAPI(title="Quit Habits Tracker API", lifespan=lifespan)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# --- API Эндпоинты ---

@app.get("/api/habits/{user_id}")
async def get_habits(user_id: int):
    async with async_session() as session:
        result = await session.execute(select(HabitDB).where(HabitDB.user_id == user_id))
        habits = result.scalars().all()
        return {
            "habits": [
                {
                    "user_id": h.user_id,
                    "type": h.type,
                    "quit_date": h.quit_date,
                    "per_day": h.per_day,
                    "unit_price": h.unit_price,
                    "unit_size": h.unit_size,
                }
                for h in habits
            ]
        }


@app.post("/api/habits")
async def save_habit(habit: HabitSchema):
    async with async_session() as session:
        user_res = await session.execute(select(UserDB).where(UserDB.user_id == habit.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            user = UserDB(user_id=habit.user_id)
            session.add(user)

        stmt = select(HabitDB).where(HabitDB.user_id == habit.user_id, HabitDB.type == habit.type)
        res = await session.execute(stmt)
        existing_habit = res.scalar_one_or_none()

        if existing_habit:
            existing_habit.quit_date = habit.quit_date
            existing_habit.per_day = habit.per_day
            existing_habit.unit_price = habit.unit_price
            existing_habit.unit_size = habit.unit_size
        else:
            new_habit = HabitDB(**habit.model_dump())
            session.add(new_habit)

        await session.commit()
    return {"ok": True}


# --- МАРШРУТЫ УДАЛЕНИЯ И СБРОСА ---

@app.delete("/api/habits/{user_id}/{habit_type}")
async def delete_habit(user_id: int, habit_type: str):
    async with async_session() as session:
        await session.execute(
            delete(HabitDB).where(HabitDB.user_id == user_id, HabitDB.type == habit_type)
        )
        await session.commit()
    return {"ok": True}


@app.delete("/api/habits/{user_id}")
async def delete_all_habits(user_id: int):
    async with async_session() as session:
        await session.execute(
            delete(HabitDB).where(HabitDB.user_id == user_id)
        )
        await session.commit()
    return {"ok": True}


# --- АНАЛИТИКА И ДРУЗЬЯ ---

@app.post("/api/relapses")
async def record_relapse(data: RelapseSchema):
    async with async_session() as session:
        relapse = RelapseDB(
            user_id=data.user_id,
            habit_type=data.habit_type,
            reason=data.reason
        )
        session.add(relapse)

        stmt = select(HabitDB).where(HabitDB.user_id == data.user_id, HabitDB.type == data.habit_type)
        res = await session.execute(stmt)
        habit = res.scalar_one_or_none()
        if habit:
            habit.quit_date = datetime.utcnow().isoformat()

        await session.commit()
    return {"ok": True}


@app.get("/api/relapses/{user_id}")
async def get_relapses(user_id: int):
    async with async_session() as session:
        res = await session.execute(
            select(RelapseDB).where(RelapseDB.user_id == user_id).order_by(RelapseDB.relapse_date.desc())
        )
        relapses = res.scalars().all()
        return {
            "relapses": [
                {
                    "id": r.id,
                    "habit_type": r.habit_type,
                    "relapse_date": r.relapse_date.isoformat(),
                    "reason": r.reason,
                }
                for r in relapses
            ]
        }


@app.post("/api/friends/add")
async def add_friend(data: AddFriendSchema):
    if data.user_id == data.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя")

    async with async_session() as session:
        stmt = select(FriendshipDB).where(
            FriendshipDB.user_id == data.user_id, FriendshipDB.friend_id == data.friend_id
        )
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            f1 = FriendshipDB(user_id=data.user_id, friend_id=data.friend_id)
            f2 = FriendshipDB(user_id=data.friend_id, friend_id=data.user_id)
            session.add_all([f1, f2])
            await session.commit()
    return {"ok": True}


@app.get("/api/friends/{user_id}")
async def get_friends(user_id: int):
    async with async_session() as session:
        stmt = select(FriendshipDB).where(FriendshipDB.user_id == user_id)
        res = await session.execute(stmt)
        friendships = res.scalars().all()

        friends_data = []
        for f in friendships:
            user_res = await session.execute(select(UserDB).where(UserDB.user_id == f.friend_id))
            friend_user = user_res.scalar_one_or_none()

            habits_res = await session.execute(select(HabitDB).where(HabitDB.user_id == f.friend_id))
            friend_habits = habits_res.scalars().all()

            friends_data.append({
                "user_id": f.friend_id,
                "first_name": friend_user.first_name if friend_user else f"User {f.friend_id}",
                "username": friend_user.username if friend_user else None,
                "habits": [
                    {"type": h.type, "quit_date": h.quit_date} for h in friend_habits
                ]
            })

        return {"friends": friends_data}


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")