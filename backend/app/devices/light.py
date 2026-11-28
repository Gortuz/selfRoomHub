"""Validación común de ajustes de luz (API y escenas)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LightSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brightness: int | None = Field(default=None, ge=1, le=100)
    color_temp: int | None = Field(default=None, ge=1000, le=10000)  # el foco acota su rango
    hue: int | None = Field(default=None, ge=0, le=360)
    saturation: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _coherente(self) -> "LightSettings":
        if (self.hue is None) != (self.saturation is None):
            raise ValueError("hue y saturation van juntos")
        if self.hue is not None and self.color_temp is not None:
            raise ValueError("usa color_temp o hue/saturation, no ambos")
        if self.brightness is None and self.color_temp is None and self.hue is None:
            raise ValueError("indica brightness, color_temp o hue/saturation")
        return self

    def args(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def describe(self) -> str:
        parts = []
        if self.brightness is not None:
            parts.append(f"brillo {self.brightness} %")
        if self.color_temp is not None:
            parts.append(f"{self.color_temp} K")
        if self.hue is not None:
            parts.append(f"color {self.hue}°/{self.saturation} %")
        return ", ".join(parts)
