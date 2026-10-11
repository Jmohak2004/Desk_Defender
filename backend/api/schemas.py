"""Typed request payloads for HTTP and WebSocket. Everything incoming is validated here."""

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, field_validator

from backend.config import CustomStructureConfig, settings


class ConnectRequest(BaseModel):
    camera_id: Union[int, str]
    width: Optional[int] = None
    height: Optional[int] = None


class CalibrationRequest(BaseModel):
    points: List[List[float]] = Field(min_length=4, max_length=4)
    frame_size: Optional[List[int]] = Field(default=None, min_length=2, max_length=2)

    @field_validator("points")
    @classmethod
    def _pairs(cls, v):
        if any(len(p) != 2 for p in v):
            raise ValueError("each point must be [x, y]")
        return v


class CustomStats(CustomStructureConfig):
    @field_validator("behavior")
    @classmethod
    def _behavior(cls, v):
        if v not in ("attack", "block", "support"):
            raise ValueError("behavior must be attack, block or support")
        return v

    @field_validator("durability")
    @classmethod
    def _dur(cls, v):
        if v is not None and not 50 <= v <= 2000:
            raise ValueError("durability must be between 50 and 2000")
        return v

    @field_validator("range")
    @classmethod
    def _rng(cls, v):
        if v is not None and not 40 <= v <= 400:
            raise ValueError("range must be between 40 and 400")
        return v

    @field_validator("damage")
    @classmethod
    def _dmg(cls, v):
        if v is not None and not 0 <= v <= 80:
            raise ValueError("damage must be between 0 and 80")
        return v

    @field_validator("fire_rate")
    @classmethod
    def _fr(cls, v):
        if v is not None and not 0.1 <= v <= 4:
            raise ValueError("fire_rate must be between 0.1 and 4")
        return v

    @field_validator("cost")
    @classmethod
    def _cost(cls, v):
        if v is not None and not 0 <= v <= 500:
            raise ValueError("cost must be between 0 and 500")
        return v


class RoleRequest(BaseModel):
    role: str
    custom: Optional[CustomStats] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in settings.game.roles:
            raise ValueError(f"role must be one of {sorted(settings.game.roles)}")
        return v


class StartRequest(BaseModel):
    player_name: Optional[str] = Field(default=None, max_length=24)


class AbilityRequest(BaseModel):
    ability: Literal["strike", "emp", "repair"]
    x: Optional[float] = Field(default=None, ge=0, le=2000)
    y: Optional[float] = Field(default=None, ge=0, le=2000)


class SimObjectCreate(BaseModel):
    kind: Literal["book", "bottle", "cup", "box", "pencil holder"]
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=700)


class SimObjectMove(BaseModel):
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=700)


# ---------------------------------------------------------------- WebSocket client messages
class _Msg(BaseModel):
    request_id: Optional[str] = Field(default=None, max_length=64)


class WsStart(_Msg):
    action: Literal["start", "restart"]
    player_name: Optional[str] = Field(default=None, max_length=24)


class WsSimple(_Msg):
    action: Literal["pause", "resume", "next_wave", "exit", "ping"]


class WsSetRole(_Msg):
    action: Literal["set_role"]
    object_id: str = Field(min_length=1, max_length=64)
    role: str
    custom: Optional[CustomStats] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in settings.game.roles:
            raise ValueError(f"role must be one of {sorted(settings.game.roles)}")
        return v


class WsRemove(_Msg):
    action: Literal["remove_object"]
    object_id: str = Field(min_length=1, max_length=64)


class WsUpgrade(_Msg):
    action: Literal["upgrade"]
    structure_id: str = Field(min_length=1, max_length=64)


class WsAbility(_Msg):
    action: Literal["ability"]
    ability: Literal["strike", "emp", "repair"]
    x: Optional[float] = Field(default=None, ge=0, le=2000)
    y: Optional[float] = Field(default=None, ge=0, le=2000)


class WsSimMove(_Msg):
    action: Literal["sim_move"]
    sim_id: str = Field(min_length=1, max_length=32)
    x: float = Field(ge=0, le=1000)
    y: float = Field(ge=0, le=700)


ClientMessage = Annotated[
    Union[WsStart, WsSimple, WsSetRole, WsRemove, WsUpgrade, WsAbility, WsSimMove],
    Field(discriminator="action"),
]
client_message_adapter = TypeAdapter(ClientMessage)
