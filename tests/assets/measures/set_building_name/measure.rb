# Minimal OpenStudio model measure for testing.
# Sets the building name to a user-specified value.
class SetBuildingName < OpenStudio::Measure::ModelMeasure
  def name
    return "Set Building Name"
  end

  def description
    return "Sets the building name to a user-specified value."
  end

  def modeler_description
    return "Uses model.getBuilding.setName()."
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    building_name = OpenStudio::Measure::OSArgument.makeStringArgument("building_name", true)
    building_name.setDisplayName("Building Name")
    building_name.setDefaultValue("Test Building")
    args << building_name

    return args
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    building_name = runner.getStringArgumentValue("building_name", user_arguments)
    model.getBuilding.setName(building_name)
    runner.registerInfo("Set building name to '#{building_name}'")

    return true
  end
end

SetBuildingName.new.registerWithApplication
