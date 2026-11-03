"""Svarsscheman för TB-extraktionen: T3 (strukturering), T3G (generella krav), T4 (fullständighet). SPEC
6.2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TBChild(BaseModel):
    description: str = Field(description="Kort produktnamn, t.ex. 'Ettgreppsblandare FMM 9000E EcoSafe'")
    manufacturer: str | None = Field(description="Fabrikat ordagrant, annars null")
    model: str | None = Field(description="Typ/modell ordagrant, annars null")
    article_no: str | None = Field(description="Tillverkarens art.nr ordagrant (inte RSK), annars null")
    rsk: str | None = Field(description="RSK-nummer, sju siffror, bara om det står i texten")
    stated_quantity: int | None = Field(description="Antal som texten anger för barnposten, annars null")
    quote: str = Field(description="Barnpostens rad ordagrant ur texten")


class TBItem(BaseModel):
    segment_id: str = Field(description="Segmentets id, t.ex. s12")
    designation: str = Field(
        description="Beteckningen ordagrant: objektbeteckning, rörbeteckning eller AMA-kod"
    )
    kind: Literal["object", "pipe"] = Field(description="object = sakvara/apparat, pipe = rörledning")
    description: str = Field(description="Kort produktnamn med fabrikat och typ, ur texten")
    manufacturer: str | None
    model: str | None
    article_no: str | None = Field(description="Tillverkarens art.nr ordagrant (inte RSK), annars null")
    rsk: str | None = Field(description="RSK-nummer, sju siffror, bara om det står i texten")
    dimension: str | None = Field(description="Dimension/storlek ordagrant, t.ex. 'DN25', '570 x 435 mm'")
    requirement_quotes: list[str] = Field(description="Tekniska krav, varje krav ordagrant ur texten")
    children: list[TBChild] = Field(description="Barnposter ur 'Härtill:'-listor, se reglerna")


class T3Response(BaseModel):
    items: list[TBItem]


class TBRule(BaseModel):
    category: str = Field(description="t.ex. isolering, material, tillbehor, tryckluft, montage")
    text: str = Field(description="Kravet kort på svenska, utan att ändra tekniska värden")
    quote: str = Field(description="Kravet ordagrant ur texten")
    applies_to: list[str] = Field(description="System, beteckningar eller rum som kravet gäller, om det står")


class T3GResponse(BaseModel):
    rules: list[TBRule]


class Missing(BaseModel):
    name: str = Field(description="Produkt/objekt som nämns men saknar egen post")
    quote: str = Field(description="Meningen där den nämns, ordagrant")
    reason: str = Field(description="Varför det borde ha en egen post, en mening")


class T4Response(BaseModel):
    missing: list[Missing]
