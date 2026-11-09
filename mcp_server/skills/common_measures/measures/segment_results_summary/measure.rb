# Bundled with openstudio-mcp for the parallel-annual skill (issue #247).

require 'json'

class SegmentResultsSummary < OpenStudio::Measure::ReportingMeasure
  FUELS = ['Electricity', 'NaturalGas'].freeze
  END_USES = ['Heating', 'Cooling', 'InteriorLights', 'ExteriorLights', 'InteriorEquipment',
              'ExteriorEquipment', 'Fans', 'Pumps', 'HeatRejection', 'Humidifier', 'HeatRecovery',
              'WaterSystems', 'Refrigeration', 'Cogeneration'].freeze
  PEAK_METER = 'Electricity:Facility'.freeze
  J_PER_KWH = 3.6e6
  OUTPUT_FILE = 'segment_results.json'.freeze

  def name
    return 'Segment Results Summary'
  end

  def description
    return 'Writes segment_results.json with monthly end uses, daily electricity and monthly peak electric demand for the kept days of a time segment.'
  end

  def modeler_description
    return 'Requests daily end-use meters and timestep Electricity:Facility, reads them from the SQL for the kept dates only (lead-in days dropped), and writes run/segment_results.json for stitch_segment_results.'
  end

  def arguments(model = nil)
    args = OpenStudio::Measure::OSArgumentVector.new
    [['keep_begin_month', 1], ['keep_begin_day', 1], ['keep_end_month', 12], ['keep_end_day', 31]].each do |arg_name, default|
      arg = OpenStudio::Measure::OSArgument.makeIntegerArgument(arg_name, true)
      arg.setDisplayName(arg_name.split('_').map(&:capitalize).join(' '))
      arg.setDescription('Kept days are reported; days outside them (the lead-in) are dropped.')
      arg.setDefaultValue(default)
      args << arg
    end
    return args
  end

  def meter_names
    FUELS.flat_map { |fuel| ["#{fuel}:Facility"] + END_USES.map { |use| "#{use}:#{fuel}" } }
  end

  def energyPlusOutputRequests(runner, user_arguments)
    super(runner, user_arguments)
    result = OpenStudio::IdfObjectVector.new
    meter_names.each { |m| result << OpenStudio::IdfObject.load("Output:Meter,#{m},Daily;").get }
    result << OpenStudio::IdfObject.load("Output:Meter,#{PEAK_METER},Timestep;").get
    return result
  end

  # [[month, day, interval_minutes, value_J], ...] for one meter in the weather-file run period.
  def meter_rows(sql, meter, frequency)
    query = "SELECT t.Month || ',' || t.Day || ',' || t.Interval || ',' || rd.Value FROM ReportData rd " \
            'JOIN Time t ON rd.TimeIndex = t.TimeIndex ' \
            'JOIN ReportDataDictionary d ON rd.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex ' \
            "WHERE d.Name = '#{meter}' AND d.ReportingFrequency = '#{frequency}' AND t.WarmupFlag = 0 " \
            'AND t.EnvironmentPeriodIndex IN (SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods WHERE EnvironmentType = 3)'
    rows = sql.execAndReturnVectorOfString(query)
    return [] unless rows.is_initialized
    rows.get.map do |row|
      m, d, interval, value = row.split(',')
      [m.to_i, d.to_i, interval.to_f, value.to_f]
    end
  end

  # Pure summary of kept days: daily meter rows per name plus peak-meter rows -> results hash.
  def summarize(daily_by_meter, peak_rows, keep_first, keep_last)
    kept = ->(m, d) { ([m, d] <=> keep_first) >= 0 && ([m, d] <=> keep_last) <= 0 }
    key = ->(m, d) { format('%02d-%02d', m, d) }
    monthly = {}
    daily_elec = {}
    daily_by_meter.each do |meter, rows|
      first, second = meter.split(':')
      fuel, use = second == 'Facility' ? [first, 'Total'] : [second, first]
      rows.each do |m, d, _interval, joules|
        next unless kept.call(m, d)
        by_fuel = (monthly[format('%02d', m)] ||= {})[fuel] ||= {}
        by_fuel[use] = by_fuel.fetch(use, 0.0) + joules / J_PER_KWH
        daily_elec[key.call(m, d)] = joules / J_PER_KWH if meter == PEAK_METER
      end
    end
    peaks = {}
    peak_rows.each do |m, d, interval, joules|
      next unless kept.call(m, d) && interval > 0
      month = format('%02d', m)
      watts = joules / (interval * 60.0)
      peaks[month] = watts if watts > peaks.fetch(month, -1.0)
    end
    return {
      'keep_begin' => key.call(*keep_first), 'keep_end' => key.call(*keep_last),
      'kept_days' => daily_elec.size,
      'units' => { 'energy' => 'kWh', 'demand' => 'W' },
      'monthly_end_uses_kwh' => monthly,
      'daily_electricity_kwh' => daily_elec.sort.to_h,
      'monthly_peak_electricity_w' => peaks
    }
  end

  def run(runner, user_arguments)
    super(runner, user_arguments)
    return false unless runner.validateUserArguments(arguments, user_arguments)

    keep_first = [runner.getIntegerArgumentValue('keep_begin_month', user_arguments),
                  runner.getIntegerArgumentValue('keep_begin_day', user_arguments)]
    keep_last = [runner.getIntegerArgumentValue('keep_end_month', user_arguments),
                 runner.getIntegerArgumentValue('keep_end_day', user_arguments)]
    sql = runner.lastEnergyPlusSqlFile
    unless sql.is_initialized
      runner.registerError('No EnergyPlus SQL file found.')
      return false
    end
    sql = sql.get

    daily = meter_names.to_h { |m| [m, meter_rows(sql, m, 'Daily')] }
    # EnergyPlus labels timestep meter data 'Zone Timestep' in the SQL.
    peak_rows = meter_rows(sql, PEAK_METER, 'Zone Timestep')
    results = summarize(daily, peak_rows, keep_first, keep_last)
    if results['kept_days'].zero?
      runner.registerError("No simulated days fall inside #{results['keep_begin']} to #{results['keep_end']}.")
      return false
    end

    path = File.join(runner.workflow.absoluteRunDir.to_s, OUTPUT_FILE)
    File.write(path, JSON.pretty_generate(results))
    total = results['daily_electricity_kwh'].values.sum
    runner.registerValue('kept_days', results['kept_days'])
    runner.registerValue('electricity_kwh', total, 'kWh')
    runner.registerFinalCondition("#{results['kept_days']} kept days, #{total.round(1)} kWh electricity; wrote #{path}.")
    return true
  end
end

SegmentResultsSummary.new.registerWithApplication
