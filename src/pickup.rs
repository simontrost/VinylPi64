use crate::config::AudioPickupUsage;
#[derive(Default)]
pub struct Pickup {
    active: bool,
    candidate: Option<f64>,
    below: Option<f64>,
    accounted: Option<f64>,
}
impl Pickup {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn observe(&mut self, level: f64, seconds: f64, now: f64, c: &AudioPickupUsage) -> f64 {
        if !c.enabled {
            self.reset();
            return 0.;
        };
        let start = now - seconds;
        if !self.active {
            if level >= c.start_threshold_dbfs {
                let candidate = *self.candidate.get_or_insert(start);
                if now - candidate >= c.start_confirm_seconds {
                    self.active = true;
                    self.below = None;
                    self.candidate = None;
                    self.accounted = Some(now);
                    return (now - candidate).max(0.);
                }
            } else {
                self.candidate = None;
            }
            return 0.;
        }
        let accounted = self.accounted.unwrap_or(start);
        if level <= c.stop_threshold_dbfs {
            let below = *self.below.get_or_insert(start);
            let stop = below + c.stop_confirm_seconds;
            if now >= stop {
                let delta = (stop - accounted).max(0.);
                self.reset();
                return delta;
            }
        } else {
            self.below = None;
        }
        self.accounted = Some(now);
        (now - accounted).max(0.)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preserves_legacy_hysteresis_and_wall_clock_accounting() {
        let mut c = crate::config::Config::default().audio.pickup_usage;
        c.start_threshold_dbfs = -40.;
        c.stop_threshold_dbfs = -50.;
        c.start_confirm_seconds = 3.;
        c.stop_confirm_seconds = 5.;
        let mut p = Pickup::default();
        assert_eq!(p.observe(-20., 4., 4., &c), 4.);
        assert_eq!(p.observe(-45., 4., 10., &c), 6.);
        assert_eq!(p.observe(-70., 4., 14., &c), 4.);
        assert_eq!(p.observe(-70., 4., 18., &c), 1.);
        assert!(!p.active);
    }
}
