from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class Product:
    id: int
    title: Optional[str]
    url: Optional[str]
    image: Optional[str]
    description: Optional[str]
    price: Optional[float]
    old_price: Optional[float]
    currency: Optional[str]
    custom_label_0: Optional[str]

    def to_record(self) -> Dict[str, Any]:
        # Preserve column order required by the template
        return {
            "ID": self.id,
            "Title": self.title or "",
            "URL": self.url or "",
            "Image": self.image or "",
            "Description": self.description or "",
            "Price": self.price,
            "Old price": self.old_price,
            "Currency": self.currency or "",
            "custom_label_0": self.custom_label_0 or "",
        }