import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    BigInteger,
    select,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base, relationship, selectinload


# ============================================================
# НАСТРОЙКА БАЗЫ ДАННЫХ
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./quit_tracker.db"
)

# Render может отдавать DATABASE_URL в старом формате postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+asyncpg://",
        1
    )

elif (
    DATABASE_URL.startswith("postgresql://")
    and not DATABASE_URL.startswith("postgresql+asyncpg://")
):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1
    )


engine = create_async_engine(
    DATABASE_URL,
    echo=False
)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)

Base = declarative_base()


# ============================================================
# МОДЕЛИ БАЗЫ ДАННЫХ
# ============================================================

class User(Base):
    __tablename__ = "users"

    # Telegram User ID
    id = Column(
        BigInteger,
        primary_key=True,
        index=True
    )

    # Настоящее имя из Telegram
    first_name = Column(
        String,
        nullable=True
    )

    # Telegram avatar URL
    photo_url = Column(
        String,
        nullable=True
    )

    habits = relationship(
        "Habit",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    relapses = relationship(
        "Relapse",
        back_populates="user",
        cascade="all, delete-orphan"
    )


class Habit(Base):
    __tablename__ = "habits"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False
    )

    type = Column(
        String,
        nullable=False
    )

    quit_date = Column(
        DateTime(timezone=True),
        nullable=False
    )

    per_day = Column(
        Float,
        default=0.0
    )

    unit_price = Column(
        Float,
        default=0.0
    )

    unit_size = Column(
        Float,
        default=1.0
    )

    user = relationship(
        "User",
        back_populates="habits"
    )


class Relapse(Base):
    __tablename__ = "relapses"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False
    )

    habit_type = Column(
        String,
        nullable=False
    )

    reason = Column(
        String,
        nullable=True
    )

    relapse_date = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    user = relationship(
        "User",
        back_populates="relapses"
    )


class Friendship(Base):
    __tablename__ = "friendships"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    user_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False
    )

    friend_id = Column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False
    )


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class HabitCreate(BaseModel):
    user_id: int
    first_name: Optional[str] = None
    photo_url: Optional[str] = None

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


class UserSyncRequest(BaseModel):
    user_id: int
    first_name: Optional[str] = None
    photo_url: Optional[str] = None


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Quit Tracker API"
)


# ============================================================
# STATIC FILES
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

async def get_db():
    async with async_session() as session:
        yield session


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )


# ============================================================
# ГЛАВНАЯ СТРАНИЦА
# ============================================================

@app.get("/")
async def read_index():
    return FileResponse(
        "static/index.html"
    )


# ============================================================
# СИНХРОНИЗАЦИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@app.post("/api/users/sync")
async def sync_user(
    data: UserSyncRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Создаёт или обновляет пользователя.

    Вызывается каждый раз при открытии Telegram Mini App.
    """

    stmt = select(User).where(
        User.id == data.user_id
    )

    result = await db.execute(stmt)

    user = result.scalar_one_or_none()

    # --------------------------------------------------------
    # Пользователя ещё нет
    # --------------------------------------------------------

    if not user:

        user = User(
            id=data.user_id,
            first_name=(
                data.first_name
                or f"User {data.user_id}"
            ),
            photo_url=data.photo_url
        )

        db.add(user)

    # --------------------------------------------------------
    # Пользователь уже есть
    # --------------------------------------------------------

    else:

        if data.first_name:
            user.first_name = data.first_name

        if data.photo_url:
            user.photo_url = data.photo_url

    await db.commit()

    return {
        "status": "ok",
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "photo_url": user.photo_url
        }
    }


# ============================================================
# ПРИВЫЧКИ
# ============================================================

@app.get("/api/habits/{user_id}")
async def get_habits(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):

    stmt = select(Habit).where(
        Habit.user_id == user_id
    )

    result = await db.execute(stmt)

    habits = result.scalars().all()

    return {
        "habits": [
            {
                "id": h.id,
                "type": h.type,
                "quit_date": h.quit_date.isoformat(),
                "per_day": h.per_day,
                "unit_price": h.unit_price,
                "unit_size": h.unit_size
            }
            for h in habits
        ]
    }


@app.post("/api/habits")
async def save_habit(
    data: HabitCreate,
    db: AsyncSession = Depends(get_db)
):

    # --------------------------------------------------------
    # Пользователь
    # --------------------------------------------------------

    stmt_user = select(User).where(
        User.id == data.user_id
    )

    result_user = await db.execute(
        stmt_user
    )

    user = result_user.scalar_one_or_none()

    name_to_set = (
        data.first_name
        or f"User {data.user_id}"
    )

    # --------------------------------------------------------
    # Создаём пользователя
    # --------------------------------------------------------

    if not user:

        user = User(
            id=data.user_id,
            first_name=name_to_set,
            photo_url=data.photo_url
        )

        db.add(user)

    # --------------------------------------------------------
    # Обновляем пользователя
    # --------------------------------------------------------

    else:

        if data.first_name:
            user.first_name = data.first_name

        if data.photo_url:
            user.photo_url = data.photo_url

    await db.commit()

    # --------------------------------------------------------
    # Удаляем старый трекер этого же типа
    # --------------------------------------------------------

    stmt_old = select(Habit).where(
        Habit.user_id == data.user_id,
        Habit.type == data.type
    )

    result_old = await db.execute(
        stmt_old
    )

    old_habit = result_old.scalar_one_or_none()

    if old_habit:
        await db.delete(old_habit)

    # --------------------------------------------------------
    # Создаём новый трекер
    # --------------------------------------------------------

    new_habit = Habit(
        user_id=data.user_id,
        type=data.type,
        quit_date=data.quit_date,
        per_day=data.per_day,
        unit_price=data.unit_price,
        unit_size=data.unit_size
    )

    db.add(new_habit)

    await db.commit()

    return {
        "status": "ok"
    }


@app.delete("/api/habits/{user_id}/{habit_type}")
async def delete_single_habit(
    user_id: int,
    habit_type: str,
    db: AsyncSession = Depends(get_db)
):

    stmt = select(Habit).where(
        Habit.user_id == user_id,
        Habit.type == habit_type
    )

    result = await db.execute(stmt)

    habit = result.scalar_one_or_none()

    if habit:

        await db.delete(habit)
        await db.commit()

    return {
        "status": "ok"
    }


@app.delete("/api/habits/{user_id}")
async def delete_all_habits(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):

    stmt = select(Habit).where(
        Habit.user_id == user_id
    )

    result = await db.execute(stmt)

    habits = result.scalars().all()

    for habit in habits:
        await db.delete(habit)

    await db.commit()

    return {
        "status": "ok"
    }


# ============================================================
# СРЫВЫ
# ============================================================

@app.post("/api/relapses")
async def log_relapse(
    data: RelapseCreate,
    db: AsyncSession = Depends(get_db)
):

    now_utc = datetime.now(
        timezone.utc
    )

    relapse = Relapse(
        user_id=data.user_id,
        habit_type=data.habit_type,
        reason=data.reason,
        relapse_date=now_utc
    )

    db.add(relapse)

    # --------------------------------------------------------
    # Сбрасываем дату отказа
    # --------------------------------------------------------

    stmt = select(Habit).where(
        Habit.user_id == data.user_id,
        Habit.type == data.habit_type
    )

    result = await db.execute(stmt)

    habit = result.scalar_one_or_none()

    if habit:
        habit.quit_date = now_utc

    await db.commit()

    return {
        "status": "ok"
    }


@app.get("/api/relapses/{user_id}")
async def get_relapses(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):

    stmt = (
        select(Relapse)
        .where(Relapse.user_id == user_id)
        .order_by(Relapse.relapse_date.desc())
    )

    result = await db.execute(stmt)

    relapses = result.scalars().all()

    return {
        "relapses": [
            {
                "id": r.id,
                "habit_type": r.habit_type,
                "reason": r.reason,
                "relapse_date": r.relapse_date.isoformat()
            }
            for r in relapses
        ]
    }


# ============================================================
# ДРУЗЬЯ
# ============================================================

@app.post("/api/friends/add")
async def add_friend(
    data: FriendAddRequest,
    db: AsyncSession = Depends(get_db)
):

    # Нельзя добавить самого себя

    if data.user_id == data.friend_id:

        raise HTTPException(
            status_code=400,
            detail="Нельзя добавить самого себя"
        )

    # --------------------------------------------------------
    # 1. Проверяем инициатора
    # --------------------------------------------------------

    stmt_user = select(User).where(
        User.id == data.user_id
    )

    result_user = await db.execute(
        stmt_user
    )

    user = result_user.scalar_one_or_none()

    if not user:

        user = User(
            id=data.user_id,
            first_name=f"User {data.user_id}"
        )

        db.add(user)

    # --------------------------------------------------------
    # 2. Проверяем друга
    # --------------------------------------------------------

    stmt_friend = select(User).where(
        User.id == data.friend_id
    )

    result_friend = await db.execute(
        stmt_friend
    )

    friend = result_friend.scalar_one_or_none()

    # --------------------------------------------------------
    # Если друг ещё не заходил
    # --------------------------------------------------------

    if not friend:

        friend = User(
            id=data.friend_id,
            first_name=f"Friend ({data.friend_id})",
            photo_url=None
        )

        db.add(friend)

    await db.commit()

    # --------------------------------------------------------
    # 3. Проверяем существующую дружбу
    # --------------------------------------------------------

    stmt_check = select(Friendship).where(
        Friendship.user_id == data.user_id,
        Friendship.friend_id == data.friend_id
    )

    result_check = await db.execute(
        stmt_check
    )

    existing_friendship = (
        result_check.scalar_one_or_none()
    )

    if not existing_friendship:

        db.add(
            Friendship(
                user_id=data.user_id,
                friend_id=data.friend_id
            )
        )

        await db.commit()

    return {
        "status": "ok",
        "message": "Друг успешно добавлен"
    }


# ============================================================
# ПОЛУЧЕНИЕ ДРУЗЕЙ
# ============================================================

@app.get("/api/friends/{user_id}")
async def get_friends(
    user_id: int,
    db: AsyncSession = Depends(get_db)
):

    stmt = select(Friendship).where(
        Friendship.user_id == user_id
    )

    result = await db.execute(stmt)

    friendships = result.scalars().all()

    friends_list = []

    for friendship in friendships:

        stmt_friend = (
            select(User)
            .options(
                selectinload(User.habits)
            )
            .where(
                User.id == friendship.friend_id
            )
        )

        result_friend = await db.execute(
            stmt_friend
        )

        friend_user = (
            result_friend.scalar_one_or_none()
        )

        if friend_user:

            friends_list.append(
                {
                    "id": friend_user.id,

                    "first_name": (
                        friend_user.first_name
                        or f"User {friend_user.id}"
                    ),

                    "photo_url": (
                        friend_user.photo_url
                    ),

                    "habits": [
                        {
                            "type": habit.type,
                            "quit_date": habit.quit_date.isoformat()
                        }
                        for habit in friend_user.habits
                    ]
                }
            )

    return {
        "friends": friends_list
    }