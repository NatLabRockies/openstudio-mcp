"""Template catalog and metadata for HVAC systems."""
from __future__ import annotations

# ASHRAE 90.1 Appendix G Baseline System Definitions
BASELINE_SYSTEMS = {
    1: {
        "name": "PTAC",
        "full_name": "Packaged Terminal Air Conditioner",
        "description": "Electric resistance heating, DX cooling, zone-level equipment",
        "heating": "Electric Resistance",
        "cooling": "DX",
        "distribution": "Zone Equipment",
        "typical_use": "Low-rise residential, motels",
    },
    2: {
        "name": "PTHP",
        "full_name": "Packaged Terminal Heat Pump",
        "description": "Heat pump heating/cooling, zone-level equipment",
        "heating": "Heat Pump",
        "cooling": "Heat Pump",
        "distribution": "Zone Equipment",
        "typical_use": "Low-rise residential, motels",
    },
    3: {
        "name": "PSZ-AC",
        "full_name": "Packaged Single Zone Air Conditioner",
        "description": "Gas furnace heating, DX cooling, single zone rooftop unit",
        "heating": "Gas Furnace",
        "cooling": "DX",
        "distribution": "Packaged Rooftop Unit",
        "typical_use": "Small commercial, retail",
    },
    4: {
        "name": "PSZ-HP",
        "full_name": "Packaged Single Zone Heat Pump",
        "description": "Heat pump heating/cooling, single zone rooftop unit",
        "heating": "Heat Pump",
        "cooling": "Heat Pump",
        "distribution": "Packaged Rooftop Unit",
        "typical_use": "Small commercial, retail",
    },
    5: {
        "name": "Packaged VAV w/ Reheat",
        "full_name": "Packaged VAV with Reheat",
        "description": "Packaged rooftop VAV with hot water reheat terminals",
        "heating": "Hot Water Reheat",
        "cooling": "DX",
        "distribution": "VAV Air Loop",
        "typical_use": "Mid-size commercial, office buildings",
    },
    6: {
        "name": "Packaged VAV w/ PFP",
        "full_name": "Packaged VAV with Parallel Fan-Powered Boxes",
        "description": "Packaged rooftop VAV with parallel fan-powered terminal boxes",
        "heating": "Electric Reheat in PFP Boxes",
        "cooling": "DX",
        "distribution": "VAV Air Loop",
        "typical_use": "Mid-size commercial, office buildings",
    },
    7: {
        "name": "VAV w/ Reheat",
        "full_name": "VAV with Reheat",
        "description": "Chiller/boiler plant with VAV and hot water reheat terminals",
        "heating": "Hot Water Reheat",
        "cooling": "Chilled Water",
        "distribution": "VAV Air Loop",
        "typical_use": "Large commercial, high-rise office",
    },
    8: {
        "name": "VAV w/ PFP",
        "full_name": "VAV with Parallel Fan-Powered Boxes",
        "description": "Chiller/boiler plant with VAV and parallel fan-powered boxes",
        "heating": "Electric Reheat in PFP Boxes",
        "cooling": "Chilled Water",
        "distribution": "VAV Air Loop",
        "typical_use": "Large commercial, high-rise office",
    },
    9: {
        "name": "Heating & Ventilation (Gas)",
        "full_name": "Heating and Ventilation",
        "description": "Gas-fired unit heaters, no mechanical cooling",
        "heating": "Gas Unit Heaters",
        "cooling": "None",
        "distribution": "Zone Equipment",
        "typical_use": "Warehouses, storage, unconditioned spaces",
    },
    10: {
        "name": "Heating & Ventilation (Electric)",
        "full_name": "Heating and Ventilation",
        "description": "Electric unit heaters, no mechanical cooling",
        "heating": "Electric Unit Heaters",
        "cooling": "None",
        "distribution": "Zone Equipment",
        "typical_use": "Warehouses, storage, unconditioned spaces",
    },
}

# Modern HVAC System Templates
MODERN_TEMPLATES = {
    "DOAS": {
        "name": "DOAS",
        "full_name": "Dedicated Outdoor Air System",
        "description": "100% OA ventilation + zone sensible conditioning (fan coils, radiant, or beams)",
        "heating": "Gas/Electric Preheat + Zone Equipment",
        "cooling": "DX Precool + Zone Equipment",
        "distribution": "DOAS Air Loop + Zone Equipment",
        "typical_use": "High-performance buildings, labs, hospitals",
        "components": ["DOAS loop", "ERV", "Zone equipment (FC/Radiant/Beams)", "CHW/HW loops"],
    },
    "VRF": {
        "name": "VRF",
        "full_name": "Variable Refrigerant Flow",
        "description": "Multi-zone heat pump with heat recovery",
        "heating": "Heat Pump",
        "cooling": "Heat Pump",
        "distribution": "VRF Outdoor Unit + Zone Terminals",
        "typical_use": "Commercial buildings, hotels, schools",
        "components": ["VRF outdoor unit", "VRF zone terminals"],
    },
    "Radiant": {
        "name": "Radiant",
        "full_name": "Low-Temperature Radiant",
        "description": "Hydronic heating/cooling via radiant surfaces + optional DOAS",
        "heating": "Low-Temp Hot Water (120°F)",
        "cooling": "Low-Temp Chilled Water (58°F)",
        "distribution": "Radiant Surfaces (Floor/Ceiling/Walls) + Optional DOAS",
        "typical_use": "High comfort zones, net-zero buildings",
        "components": ["Radiant surfaces", "Low-temp CHW/HW loops", "Optional DOAS"],
    },
}


def get_baseline_system_info(system_type: int) -> dict:
    """Get metadata for ASHRAE baseline system type."""
    if system_type not in BASELINE_SYSTEMS:
        return {"ok": False, "error": f"Invalid system type: {system_type}. Must be 1-10."}
    return {"ok": True, "system": BASELINE_SYSTEMS[system_type]}


def get_template_info(template_name: str) -> dict:
    """Get metadata for modern HVAC template."""
    if template_name not in MODERN_TEMPLATES:
        return {"ok": False, "error": f"Template '{template_name}' not found."}
    return {"ok": True, "template": MODERN_TEMPLATES[template_name]}


def list_all_templates() -> dict:
    """List all available HVAC templates (baseline + modern)."""
    baseline = [
        {
            "category": "baseline",
            "system_type": k,
            "name": v["name"],
            "description": v["description"],
        }
        for k, v in BASELINE_SYSTEMS.items()
    ]

    modern = [
        {
            "category": "modern",
            "name": k,
            "description": v["description"],
        }
        for k, v in MODERN_TEMPLATES.items()
    ]

    return {
        "ok": True,
        "baseline_systems": baseline,
        "modern_templates": modern,
        "total_count": len(baseline) + len(modern),
    }
