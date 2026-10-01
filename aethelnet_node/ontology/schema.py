from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class EntityType(BaseModel):
    type_id: str
    name: str
    description: str = ""
    color: str = "#FFFFFF"
    icon: str = "circle"
    required_properties: List[str] = Field(default_factory=list)
    optional_properties: List[str] = Field(default_factory=list)

class RelationType(BaseModel):
    type_id: str
    name: str
    description: str = ""
    color: str = "#FFFFFF"
    is_directional: bool = True
    allowed_source_types: List[str] = Field(default_factory=list)
    allowed_target_types: List[str] = Field(default_factory=list)
    is_conflict_candidate: bool = False

class ConflictRule(BaseModel):
    rule_id: str
    name: str
    conflicting_relations: List[str]
    severity: str = "critical"  # "critical", "suspicious", "advisory"
    description: str = ""

class AppOntology(BaseModel):
    app_id: str
    name: str
    version: str = "1.0.0"
    domain: str
    description: str = ""
    icon: str = "grid"
    entities: Dict[str, EntityType] = Field(default_factory=dict)
    relations: Dict[str, RelationType] = Field(default_factory=dict)
    conflict_rules: List[ConflictRule] = Field(default_factory=list)
    default_view: str = "graph"  # "graph", "matrix", "dossier", "timeline"
