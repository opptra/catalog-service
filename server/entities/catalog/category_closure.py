from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from entities.catalog.base import Base


class CategoryClosure(Base):
    __tablename__ = "category_closure"
    __table_args__ = (
        Index("idx_closure_descendant", "descendant_id"),
        Index("idx_closure_ancestor", "ancestor_id"),
    )

    ancestor_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    descendant_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
