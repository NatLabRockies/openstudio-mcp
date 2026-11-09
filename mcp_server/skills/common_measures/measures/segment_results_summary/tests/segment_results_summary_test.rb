require 'openstudio'
require 'minitest/autorun'
require_relative '../measure'

class SegmentResultsSummaryTest < Minitest::Test
  KWH = 3.6e6

  def test_requests_daily_end_use_meters_and_timestep_peak
    # Validates: the meters the summary reads are requested, at the frequencies its SQL queries expect
    measure = SegmentResultsSummary.new
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    requests = measure.energyPlusOutputRequests(runner, OpenStudio::Measure.convertOSArgumentVectorToMap(measure.arguments))
    texts = requests.map { |o| [o.getString(0).get, o.getString(1).get] }
    assert_equal(31, texts.size)
    assert_includes(texts, ['Electricity:Facility', 'Daily'])
    assert_includes(texts, ['Heating:NaturalGas', 'Daily'])
    assert_includes(texts, ['Electricity:Facility', 'Timestep'])
  end

  def test_summary_drops_lead_in_days
    # Validates: lead-in days (Jan 29-30) are excluded from monthly end uses, daily electricity and peaks,
    # and energy is converted J -> kWh, peak J per 10-min interval -> W
    daily = {
      'Electricity:Facility' => [[1, 29, 1440, 99 * KWH], [1, 30, 1440, 99 * KWH], [1, 31, 1440, 10 * KWH], [2, 1, 1440, 20 * KWH]],
      'Heating:Electricity' => [[1, 30, 1440, 50 * KWH], [1, 31, 1440, 4 * KWH], [2, 1, 1440, 6 * KWH]],
      'NaturalGas:Facility' => [[1, 31, 1440, 7 * KWH]]
    }
    peak = [[1, 30, 10, 600_000_000.0], [1, 31, 10, 600_000.0], [2, 1, 10, 1_200_000.0]]
    r = SegmentResultsSummary.new.summarize(daily, peak, [1, 31], [2, 1])
    assert_equal('01-31', r['keep_begin'])
    assert_equal(2, r['kept_days'])
    assert_equal({ '01-31' => 10.0, '02-01' => 20.0 }, r['daily_electricity_kwh'])
    assert_equal({ 'Electricity' => { 'Total' => 10.0, 'Heating' => 4.0 }, 'NaturalGas' => { 'Total' => 7.0 } }, r['monthly_end_uses_kwh']['01'])
    assert_equal({ 'Electricity' => { 'Total' => 20.0, 'Heating' => 6.0 } }, r['monthly_end_uses_kwh']['02'])
    assert_in_delta(1000.0, r['monthly_peak_electricity_w']['01'], 1e-9)
    assert_in_delta(2000.0, r['monthly_peak_electricity_w']['02'], 1e-9)
  end
end
