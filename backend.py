import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, BigInteger, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship, selectinload

# --- НАСТРОЙКА БАЗЫ ДАННЫХ ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./quit_tracker.db")

# Адаптация URI для asyncpg, если на Render используется postgres:// или postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()


# --- МОДЕЛИ СУБД ---
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)  # Telegram User ID
    first_name = Column(String, nullable=True)

    habits = relationship("Habit", back_populates="user", cascade="all, delete-orphan")
    relapses = relationship("Relapse", back_populates="user", cascade="all, delete-orphan")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # 'vape' или 'alcohol'
    quit_date = Column(DateTime, nullable=False)
    per_day = Column(Float, default=0.0)
    unit_price = Column(Float, default=0.0)
    unit_size = Column(Float, default=1.0)

    user = relationship("User", back_populates="habits")


class Relapse(Base):
    __tablename__ = "relapses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    habit_type = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    relapse_date = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="relapses")


class Friendship(Base):
    __tablename__ = "friendships"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    friend_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)


# --- PYDANTIC СХЕМЫ ---
class HabitCreate(BaseModel):
    user_id: int
    type: str
    quit_date: datetime
    per_day: float
    unit_price: float
    unit_size: float


class RelapseCreate(BaseModel):
    user_id: int
    habit_type: str
    reason: Optional[str] = "Срыв"


class FriendAddRequest(BaseModel):
    user_id: int
    friend_id: int


# --- ИНИЦИАЛИЗА FASTAPI ---
app = FastAPI(title="Quit Tracker API")

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")


async def get_db():
    async with async_session() as session:
        yield session


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# --- ЭНДПОИНТЫ ИНТЕРФЕЙСА ---
@app.get("/")
async def read_index():
    return FileResponse("static/index.html")


# --- ЭНДПОИНТЫ ПРИВЫЧЕК ---
@app.get("/api/habits/{user_id}")
async def get_habits(user_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Habit).where(Habit.user_id == user_id)
    res = await db.execute(stmt)
    habits = res.scalars().all()
    
    return {
        "habits": [
            {
                "id": h.id,
                "type": h.type,
                "quit_date": h.quit_date.isoformat(),
                "per_day": h.per_day,
                "unit_price": h.unit_price,
                "unit_size": h.unit_size
            } for h in habits
        ]
    }


@app.post("/api/habits")
async def save_habit(data: HabitCreate, db: AsyncSession = Depends(get_db)):
    # Проверяем или создаем юзера
    stmt_user = select(User).where(User.id == data.user_id)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()

    if not user:
        user = User(id=data.user_id, first_name=f"User {data.user_id}")
        db.add(user)
        await db.commit()

    # Удаляем старый трекер этого же типа, если был
    stmt_old = select(Habit).where(Habit.user_id == data.user_id, Habit.type == data.type)
    res_old = await db.execute(stmt_old)
    old_habit = res_old.scalar_one_or_none()
    if old_habit:
        await db.delete(old_habit)

    new_habit = Habit(
        user_id=data.user_id,
        type=data.type,
        quit_date=data.quit_date.replace(tzinfo=None),
        per_day=data.per_day,
        unit_price=data.unit_price,
        unit_size=data.unit_size
    )
    db.add(new_habit)
    await db.commit()

    return {"status": "ok"}


@app.delete("/api/habits/{user_id}/{habit_type}")
async def delete_habit(user_id: int, habit_type: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Habit).where(Habit.user_id == user_id, Habit.type == habit_type)
    res = await db.execute(stmt)
    habit = res.scalar_one_or_none()
    if habit:
        await db.delete(habit)
        await db.commit()
    return {"status": "ok"}


@app.delete("/api/habits/{user_id}")
async def delete_all_habits(user_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Habit).where(Habit.user_id == user_id)
    res = await db.execute(stmt)
    for h in res.scalars().all():
        await db.delete(h)
    await db.commit()
    return {"status": "ok"}


# --- ЭНДПОИНТЫ СРЫВОВ ---
@app.post("/api/relapses")
async def log_relapse(data: RelapseCreate, db: AsyncSession = Depends(get_db)):
    # Логируем срыв
    relapse = Relapse(
        user_id=data.user_id,
        habit_type=data.habit_type,
        reason=data.reason,
        relapse_date=datetime.utcnow()
    )
    db.add(relapse)

    # Сбрасываем дату отказа на текущее время
    stmt = select(Habit).where(Habit.user_id == data.user_id, Habit.type == data.habit_type)
    res = await db.execute(stmt)
    habit = res.scalar_one_or_none()
    if habit:
        habit.quit_date = datetime.utcnow()

    await db.commit()
    return {"status": "ok"}


@app.get("/api/relapses/{user_id}")
async def get_relapses(user_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Relapse).where(Relapse.user_id == user_id).order_by(Relapse.relapse_date.desc())
    res = await db.execute(stmt)
    relapses = res.scalars().all()
    
    return {
        "relapses": [
            {
                "id": r.id,
                "habit_type": r.habit_type,
                "reason": r.reason,
                "relapse_date": r.relapse_date.isoformat()
            } for r in relapses
        ]
    }


# --- ЭНДПОИНТЫ ДРУЗЕЙ ---
@app.post("/api/friends/add")
async def add_friend(data: FriendAddRequest, db: AsyncSession = Depends(get_db)):
    if data.user_id == data.friend_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя")

    # 1. Проверяем/создаем инициатора
    stmt_user = select(User).where(User.id == data.user_id)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()
    if not user:
        user = User(id=data.user_id, first_name=f"User {data.user_id}")
        db.add(user)

    # 2. Проверяем/создаем пользователя-друга
    stmt_friend = select(User).where(User.id == data.friend_id)
    res_friend = await db.execute(stmt_friend)
    friend = res_friend.scalar_one_or_none()
    if not friend:
        friend = User(id=data.friend_id, first_name=f"Friend ({data.friend_id})")
        db.add(friend)

    await db.commit()

    # 3. Добавляем двустороннюю или одностороннюю связь
    stmt_check = select(Friendship).where(
        Friendship.user_id == data.user_id,
        Friendship.friend_id == data.friend_id
    )
    res_check = await db.execute(stmt_check)
    if not res_check.scalar_one_or_none():
        db.add(Friendship(user_id=data.user_id, friend_id=data.friend_id))
        await db.commit()

    return {"status": "ok", "message": "Друг успешно добавлен"}


@app.get("/api/friends/{user_id}")
async def get_friends(user_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(Friendship).where(Friendship.user_id == user_id)
    res = await db.execute(stmt)
    friendships = res.scalars().all()

    friends_list = []
    for f in friendships:
        stmt_f = select(User).options(selectinload(User.habits)).where(User.id == f.friend_id)
        res_f = await db.execute(stmt_f)
        friend_user = res_f.scalar_one_or_none()

        if friend_user:
            friends_list.append({
                "id": friend_user.id,
                "first_name": friend_user.first_name or f"User {friend_user.id}",
                "habits": [
                    {
                        "type": h.type,
                        "quit_date": h.quit_date.isoformat()
                    } for h in friend_user.habits
                ]
            })

    return {"friends": friends_list}