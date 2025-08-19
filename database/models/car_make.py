from datetime import datetime, UTC
from typing import List, TYPE_CHECKING

from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column

from database.models import Base


if TYPE_CHECKING:
    from database.models.car_model import Model

class Make(Base):
    __tablename__ = "make"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(), index=True)
    slug: Mapped[str] = mapped_column(String(), index=True)

    models: Mapped[List["Model"]] = relationship("Model", back_populates="make")


