## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Assign 90.1-2019 Office WholeBuilding - Sm Office to every conditioned space" | assign_space_type_simple | standards_template=90.1-2019, standards_building_type=Office, standards_space_type present |
| "Attribute one standards space type to all conditioned spaces in this office" | assign_space_type_simple | standards_template present, standards_building_type present, standards_space_type present |
| "Run the space type wizard for this mixed-use building" | start_space_type_wizard | — |
| "Help me assign different standards space types to the conditioned spaces" | start_space_type_wizard | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "What space types already exist in the model?" | assign_space_type_simple, start_space_type_wizard, assign_space_type_batch | list_model_objects, get_space_type_details |
| "Show the details for the Office Space Type" | assign_space_type_simple, start_space_type_wizard, assign_space_type_batch | get_space_type_details, list_model_objects |
| "Create typical loads for this office building" | assign_space_type_simple, start_space_type_wizard, assign_space_type_batch | create_typical_building, create_people_definition, create_lights_definition |
