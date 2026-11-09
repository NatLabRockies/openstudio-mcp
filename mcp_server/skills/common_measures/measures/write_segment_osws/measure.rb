# Bundled with openstudio-mcp for the parallel-annual skill (issue #247).

require 'date'
require 'fileutils'
require 'json'

class WriteSegmentOsws < OpenStudio::Measure::ModelMeasure
  def name
    return 'Write Segment OSWs'
  end

  def description
    return 'Writes one OSW per time segment of the run period, with a seasonal lead-in, for parallel annual simulation.'
  end

  def modeler_description
    return 'Splits the model RunPeriod into equal segments. Each OSW runs the seed model with set_run_period_and_save (kept days plus lead-in), set_warmup_days and segment_results_summary (kept days only).'
  end

  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new
    add = lambda do |arg, display, desc, default|
      arg.setDisplayName(display)
      arg.setDescription(desc)
      arg.setDefaultValue(default) unless default.nil?
      args << arg
    end
    add.call(OpenStudio::Measure::OSArgument.makeStringArgument('seed_osm_path', true), 'Seed OSM path',
             'Absolute path of the saved, hard-sized model every segment runs.', nil)
    add.call(OpenStudio::Measure::OSArgument.makeStringArgument('weather_file', false), 'Weather file',
             'Absolute EPW path written into each OSW. Empty: the seed model weather file is used.', '')
    add.call(OpenStudio::Measure::OSArgument.makeIntegerArgument('number_of_segments', true), 'Number of segments',
             'Equal-length segments the run period is split into.', 12)
    add.call(OpenStudio::Measure::OSArgument.makeIntegerArgument('first_warmup_days', true), 'First segment warmup days',
             'Warmup days for segment 1, which has no lead-in.', 7)
    add.call(OpenStudio::Measure::OSArgument.makeIntegerArgument('warmup_days', true), 'Other segments warmup days',
             'Warmup days for every later segment.', 1)
    add.call(OpenStudio::Measure::OSArgument.makeIntegerArgument('long_lead_in_days', true), 'Long lead-in days',
             'Real-weather days simulated and dropped before a segment that starts outside the short lead-in months.', 7)
    add.call(OpenStudio::Measure::OSArgument.makeIntegerArgument('short_lead_in_days', true), 'Short lead-in days',
             'Lead-in days for a segment that starts in a short lead-in month.', 2)
    add.call(OpenStudio::Measure::OSArgument.makeStringArgument('short_lead_in_months', true), 'Short lead-in months',
             'Comma-separated months (1-12) whose segments get the short lead-in.', '6,7,8,9')
    add.call(OpenStudio::Measure::OSArgument.makeStringArgument('measures_dir', true), 'Measures directory',
             'Directory holding set_run_period_and_save, set_warmup_days and segment_results_summary.', '/opt/common-measures')
    add.call(OpenStudio::Measure::OSArgument.makeStringArgument('output_dir', false), 'Output directory',
             'Where segment_NN/segment_NN.osw files are written. Empty: segments/ next to this workflow.', '')
    return args
  end

  # [[keep_first, keep_last, run_first, warmup_days], ...] for each segment.
  def plan_segments(first, last, count, first_warmup, warmup, long_lead, short_lead, short_months)
    days = (last - first).to_i + 1
    year_start = Date.new(first.year, 1, 1)
    (0...count).map do |k|
      keep_first = first + (k * days) / count
      keep_last = first + ((k + 1) * days) / count - 1
      if k.zero?
        [keep_first, keep_last, keep_first, first_warmup]
      else
        lead = short_months.include?(keep_first.month) ? short_lead : long_lead
        [keep_first, keep_last, [keep_first - lead, year_start].max, warmup]
      end
    end
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    return false unless runner.validateUserArguments(arguments(model), user_arguments)

    seed = runner.getStringArgumentValue('seed_osm_path', user_arguments).strip
    weather = runner.getStringArgumentValue('weather_file', user_arguments).strip
    count = runner.getIntegerArgumentValue('number_of_segments', user_arguments)
    ints = ['first_warmup_days', 'warmup_days', 'long_lead_in_days', 'short_lead_in_days'].map do |n|
      runner.getIntegerArgumentValue(n, user_arguments)
    end
    months_text = runner.getStringArgumentValue('short_lead_in_months', user_arguments)
    measures_dir = runner.getStringArgumentValue('measures_dir', user_arguments).strip
    output_dir = runner.getStringArgumentValue('output_dir', user_arguments).strip
    output_dir = File.join(runner.workflow.absoluteRootDir.to_s, 'segments') if output_dir.empty?

    if seed.empty?
      runner.registerError('seed_osm_path is required.')
      return false
    end
    if ints[0] < 1 || ints[1] < 1 || ints[2] < 0 || ints[3] < 0
      runner.registerError('Warmup days must be 1 or more and lead-in days 0 or more.')
      return false
    end
    short_months = months_text.split(',').map(&:strip).reject(&:empty?).map(&:to_i)
    unless short_months.all? { |m| m.between?(1, 12) }
      runner.registerError("short_lead_in_months must list months 1-12, got '#{months_text}'.")
      return false
    end

    rp = model.getRunPeriod
    year = model.getYearDescription.assumedYear
    first = Date.new(year, rp.getBeginMonth, rp.getBeginDayOfMonth)
    last = Date.new(year, rp.getEndMonth, rp.getEndDayOfMonth)
    days = (last - first).to_i + 1
    unless count.between?(1, days)
      runner.registerError("number_of_segments must be between 1 and #{days} (days in the run period), got #{count}.")
      return false
    end
    runner.registerInitialCondition("Run period #{first} to #{last} (#{days} days), #{count} segments.")

    width = [2, count.to_s.size].max
    plan_segments(first, last, count, *ints, short_months).each_with_index do |(keep_first, keep_last, run_first, warmup), k|
      label = format("segment_%0#{width}d", k + 1)
      osw = { 'seed_file' => seed, 'measure_paths' => [measures_dir], 'steps' => [
        { 'measure_dir_name' => 'set_run_period_and_save', 'arguments' => {
          'begin_month' => run_first.month, 'begin_day' => run_first.day,
          'end_month' => keep_last.month, 'end_day' => keep_last.day } },
        { 'measure_dir_name' => 'set_warmup_days', 'arguments' => { 'warmup_days' => warmup } },
        { 'measure_dir_name' => 'segment_results_summary', 'arguments' => {
          'keep_begin_month' => keep_first.month, 'keep_begin_day' => keep_first.day,
          'keep_end_month' => keep_last.month, 'keep_end_day' => keep_last.day } }
      ] }
      osw['weather_file'] = weather unless weather.empty?
      # One folder per OSW: run_osw copies the OSW's whole folder into each run.
      dir = File.join(output_dir, label)
      FileUtils.mkdir_p(dir)
      File.write(File.join(dir, "#{label}.osw"), JSON.pretty_generate(osw))
      runner.registerInfo("#{label}: keep #{keep_first} to #{keep_last}, run from #{run_first}, #{warmup} warmup days.")
    end
    runner.registerValue('segments_written', count)
    runner.registerFinalCondition("Wrote #{count} OSWs as #{output_dir}/segment_NN/segment_NN.osw (NN = 01..#{format("%0#{width}d", count)}).")
    return true
  end
end

WriteSegmentOsws.new.registerWithApplication
