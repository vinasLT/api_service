from sqlalchemy import  Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from database.models import Base


class Model(Base):
    __tablename__ = "model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(), index=True)
    slug: Mapped[str] = mapped_column(String(), index=True)
    make_id: Mapped[int] = mapped_column(Integer, ForeignKey("make.id", ondelete="CASCADE"), nullable=False)
