use base64::engine::general_purpose;
use base64::Engine;
use byteorder::{LittleEndian, WriteBytesExt};
use crc32fast::Hasher;
use std::cmp::Ordering;
use std::collections::HashMap;
use std::error::Error;
use std::io::{Cursor, Seek, SeekFrom, Write};

const DATA_URI_PREFIX: &str = "data:audio/vnd.shazam.sig;base64,";

pub struct FrequencyPeak {
    pub fft_pass_number: u32,
    pub peak_magnitude: u16,
    pub corrected_peak_frequency_bin: u16,
}

#[derive(Hash, Eq, PartialEq, Debug, Clone, Copy)]
pub enum FrequencyBand {
    _250_520 = 0,
    _520_1450 = 1,
    _1450_3500 = 2,
    _3500_5500 = 3,
}

impl Ord for FrequencyBand {
    fn cmp(&self, other: &Self) -> Ordering {
        (*self as i32).cmp(&(*other as i32))
    }
}

impl PartialOrd for FrequencyBand {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

pub struct DecodedSignature {
    pub sample_rate_hz: u32,
    pub number_samples: u32,
    pub frequency_band_to_sound_peaks: HashMap<FrequencyBand, Vec<FrequencyPeak>>,
}

impl DecodedSignature {
    pub fn encode_to_binary(&self) -> Result<Vec<u8>, Box<dyn Error>> {
        let mut cursor = Cursor::new(vec![]);

        // The names below are the fields of `RawSignatureHeader` in the project this was
        //  ported from, which says what each one holds. Only its decoder needed the struct.
        //  https://github.com/marin-m/SongRec/blob/50b72aab457718fd0b2a814aa002149cea37453a/src/core/fingerprinting/signature_format.rs#L24

        cursor.write_u32::<LittleEndian>(0xcafe2580)?; // magic1
        cursor.write_u32::<LittleEndian>(0)?; // crc32 - Will write later
        cursor.write_u32::<LittleEndian>(0)?; // size_minus_header - Will write later
        cursor.write_u32::<LittleEndian>(0x94119c00)?; // magic2

        cursor.write_u32::<LittleEndian>(0)?; // void1
        cursor.write_u32::<LittleEndian>(0)?;
        cursor.write_u32::<LittleEndian>(0)?;

        cursor.write_u32::<LittleEndian>(
            match self.sample_rate_hz {
                8000 => 1,
                11025 => 2,
                16000 => 3,
                32000 => 4,
                44100 => 5,
                48000 => 6,
                _ => {
                    panic!("Invalid sample rate passed when encoding Shazam packet");
                }
            } << 27,
        )?; // shifted_sample_rate_id

        cursor.write_u32::<LittleEndian>(0)?; // void2
        cursor.write_u32::<LittleEndian>(0)?;
        cursor.write_u32::<LittleEndian>(
            self.number_samples + (self.sample_rate_hz as f32 * 0.24) as u32,
        )?; // number_samples_plus_divided_sample_rate
        cursor.write_u32::<LittleEndian>((15 << 19) + 0x40000)?; // fixed_value

        cursor.write_u32::<LittleEndian>(0x40000000)?;
        cursor.write_u32::<LittleEndian>(0)?; // size_minus_header - Will write later

        let mut sorted_iterator: Vec<_> = self.frequency_band_to_sound_peaks.iter().collect();
        sorted_iterator.sort_by(|x, y| x.0.cmp(y.0));

        for (frequency_band, frequency_peaks) in sorted_iterator {
            let mut peaks_cursor = Cursor::new(vec![]);

            let mut fft_pass_number = 0;

            for frequency_peak in frequency_peaks {
                assert!(frequency_peak.fft_pass_number >= fft_pass_number);

                if frequency_peak.fft_pass_number - fft_pass_number >= 255 {
                    peaks_cursor.write_u8(0xff)?;
                    peaks_cursor.write_u32::<LittleEndian>(frequency_peak.fft_pass_number)?;

                    fft_pass_number = frequency_peak.fft_pass_number;
                }

                peaks_cursor.write_u8((frequency_peak.fft_pass_number - fft_pass_number) as u8)?;

                peaks_cursor.write_u16::<LittleEndian>(frequency_peak.peak_magnitude)?;
                peaks_cursor
                    .write_u16::<LittleEndian>(frequency_peak.corrected_peak_frequency_bin)?;

                fft_pass_number = frequency_peak.fft_pass_number;
            }

            let peaks_buffer = peaks_cursor.into_inner();

            cursor.write_u32::<LittleEndian>(0x60030040 + *frequency_band as u32)?;
            cursor.write_u32::<LittleEndian>(peaks_buffer.len() as u32)?;
            cursor.write_all(&peaks_buffer)?;
            for _padding_index in 0..((4 - peaks_buffer.len() as u32 % 4) % 4) {
                cursor.write_u8(0)?;
            }
        }

        let buffer_size = cursor.position() as u32;

        cursor.seek(SeekFrom::Start(8))?;
        cursor.write_u32::<LittleEndian>(buffer_size - 48)?;

        cursor.seek(SeekFrom::Start(48 + 4))?;
        cursor.write_u32::<LittleEndian>(buffer_size - 48)?;

        cursor.seek(SeekFrom::Start(4))?;
        let mut hasher = Hasher::new();
        hasher.update(&cursor.get_ref()[8..]);
        cursor.write_u32::<LittleEndian>(hasher.finalize())?; // crc32

        Ok(cursor.into_inner())
    }

    pub fn encode_to_uri(&self) -> Result<String, Box<dyn Error>> {
        Ok(format!(
            "{}{}",
            DATA_URI_PREFIX,
            general_purpose::STANDARD.encode(self.encode_to_binary()?)
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Offsets into the 48-byte header, in the order `encode_to_binary` writes it.
    const MAGIC1_OFFSET: usize = 0;
    const CRC32_OFFSET: usize = 4;
    const SIZE_MINUS_HEADER_OFFSET: usize = 8;
    const MAGIC2_OFFSET: usize = 12;

    const SHIFTED_SAMPLE_RATE_ID_OFFSET: usize = 28;
    const NUMBER_SAMPLES_PLUS_OFFSET: usize = 40;
    const FIXED_VALUE_OFFSET: usize = 44;
    const HEADER_LENGTH: usize = 48;

    // The body repeats its own length one `u32` in, and the bands start after that.
    const BODY_SIZE_OFFSET: usize = HEADER_LENGTH + 4;
    const FIRST_BAND_OFFSET: usize = HEADER_LENGTH + 8;

    const SAMPLE_RATE_HZ: u32 = 16000;

    fn read_u32(encoded: &[u8], offset: usize) -> u32 {
        u32::from_le_bytes(encoded[offset..offset + 4].try_into().unwrap())
    }

    fn signature_of(bands: Vec<(FrequencyBand, Vec<FrequencyPeak>)>) -> DecodedSignature {
        DecodedSignature {
            sample_rate_hz: SAMPLE_RATE_HZ,
            number_samples: 128000,
            frequency_band_to_sound_peaks: bands.into_iter().collect(),
        }
    }

    // Walks the band list the way a reader of the format has to: a marker, a length,
    //  that many bytes of peaks, then padding up to the next multiple of four.
    fn band_markers(encoded: &[u8]) -> Vec<u32> {
        let mut markers = vec![];
        let mut offset = FIRST_BAND_OFFSET;

        while offset < encoded.len() {
            markers.push(read_u32(encoded, offset));

            let peaks_length = read_u32(encoded, offset + 4) as usize;
            offset += 8 + peaks_length + (4 - peaks_length % 4) % 4;
        }

        markers
    }

    #[test]
    fn the_header_carries_the_two_magic_values_and_the_sample_rate_id() {
        let encoded = signature_of(vec![]).encode_to_binary().unwrap();

        assert_eq!(read_u32(&encoded, MAGIC1_OFFSET), 0xcafe2580);
        assert_eq!(read_u32(&encoded, MAGIC2_OFFSET), 0x94119c00);
        // 16 kHz is sample-rate id 3, and the field holds it shifted left by 27.
        assert_eq!(read_u32(&encoded, SHIFTED_SAMPLE_RATE_ID_OFFSET), 3 << 27);
        assert_eq!(read_u32(&encoded, FIXED_VALUE_OFFSET), (15 << 19) + 0x40000);
    }

    #[test]
    fn the_sample_count_is_padded_by_240_ms_worth_of_samples() {
        let encoded = signature_of(vec![]).encode_to_binary().unwrap();

        assert_eq!(
            read_u32(&encoded, NUMBER_SAMPLES_PLUS_OFFSET),
            128000 + (SAMPLE_RATE_HZ as f32 * 0.24) as u32,
        );
    }

    #[test]
    fn every_supported_sample_rate_has_its_own_id() {
        for (sample_rate_hz, sample_rate_id) in [
            (8000, 1),
            (11025, 2),
            (16000, 3),
            (32000, 4),
            (44100, 5),
            (48000, 6),
        ] {
            let encoded = DecodedSignature {
                sample_rate_hz,
                number_samples: 0,
                frequency_band_to_sound_peaks: HashMap::new(),
            }
            .encode_to_binary()
            .unwrap();

            assert_eq!(
                read_u32(&encoded, SHIFTED_SAMPLE_RATE_ID_OFFSET),
                sample_rate_id << 27,
            );
        }
    }

    #[test]
    #[should_panic(expected = "Invalid sample rate")]
    fn an_unsupported_sample_rate_panics() {
        let signature = DecodedSignature {
            sample_rate_hz: 22050,
            number_samples: 0,
            frequency_band_to_sound_peaks: HashMap::new(),
        };

        signature.encode_to_binary().unwrap();
    }

    #[test]
    fn both_length_fields_hold_everything_after_the_header() {
        let encoded = signature_of(vec![(
            FrequencyBand::_250_520,
            vec![FrequencyPeak {
                fft_pass_number: 0,
                peak_magnitude: 0x1234,
                corrected_peak_frequency_bin: 0x5678,
            }],
        )])
        .encode_to_binary()
        .unwrap();

        let body_length = (encoded.len() - HEADER_LENGTH) as u32;

        assert_eq!(read_u32(&encoded, SIZE_MINUS_HEADER_OFFSET), body_length);
        assert_eq!(read_u32(&encoded, BODY_SIZE_OFFSET), body_length);
    }

    #[test]
    fn the_crc32_covers_every_byte_after_itself() {
        let encoded = signature_of(vec![(
            FrequencyBand::_1450_3500,
            vec![FrequencyPeak {
                fft_pass_number: 3,
                peak_magnitude: 7,
                corrected_peak_frequency_bin: 9,
            }],
        )])
        .encode_to_binary()
        .unwrap();

        let mut hasher = Hasher::new();
        hasher.update(&encoded[CRC32_OFFSET + 4..]);

        assert_eq!(read_u32(&encoded, CRC32_OFFSET), hasher.finalize());
    }

    #[test]
    fn a_peak_is_written_as_a_delta_from_the_previous_fft_pass() {
        let encoded = signature_of(vec![(
            FrequencyBand::_250_520,
            vec![
                FrequencyPeak {
                    fft_pass_number: 0,
                    peak_magnitude: 0x1234,
                    corrected_peak_frequency_bin: 0x5678,
                },
                FrequencyPeak {
                    fft_pass_number: 7,
                    peak_magnitude: 0x4321,
                    corrected_peak_frequency_bin: 0x8765,
                },
            ],
        )])
        .encode_to_binary()
        .unwrap();

        assert_eq!(
            &encoded[FIRST_BAND_OFFSET + 8..FIRST_BAND_OFFSET + 18],
            &[0, 0x34, 0x12, 0x78, 0x56, 7, 0x21, 0x43, 0x65, 0x87],
        );
    }

    #[test]
    fn a_gap_of_255_passes_or_more_is_escaped_with_an_absolute_pass_number() {
        let encoded = signature_of(vec![(
            FrequencyBand::_250_520,
            vec![
                FrequencyPeak {
                    fft_pass_number: 0,
                    peak_magnitude: 1,
                    corrected_peak_frequency_bin: 2,
                },
                FrequencyPeak {
                    fft_pass_number: 300,
                    peak_magnitude: 3,
                    corrected_peak_frequency_bin: 4,
                },
            ],
        )])
        .encode_to_binary()
        .unwrap();

        // A delta byte cannot express 300, so the escape writes the pass number whole
        //  and the delta that follows it is zero.
        assert_eq!(
            &encoded[FIRST_BAND_OFFSET + 13..FIRST_BAND_OFFSET + 23],
            &[0xff, 0x2c, 0x01, 0x00, 0x00, 0, 3, 0, 4, 0],
        );
    }

    #[test]
    fn a_band_is_padded_to_a_multiple_of_four_bytes() {
        let encoded = signature_of(vec![(
            FrequencyBand::_250_520,
            vec![FrequencyPeak {
                fft_pass_number: 0,
                peak_magnitude: 1,
                corrected_peak_frequency_bin: 2,
            }],
        )])
        .encode_to_binary()
        .unwrap();

        // One peak is five bytes, so three bytes of padding follow it.
        assert_eq!(read_u32(&encoded, FIRST_BAND_OFFSET + 4), 5);
        assert_eq!(encoded.len(), FIRST_BAND_OFFSET + 8 + 5 + 3);
        assert_eq!(&encoded[encoded.len() - 3..], &[0, 0, 0]);
    }

    #[test]
    fn bands_are_written_in_ascending_order_whatever_the_map_hands_back() {
        let peak = || FrequencyPeak {
            fft_pass_number: 0,
            peak_magnitude: 1,
            corrected_peak_frequency_bin: 2,
        };

        // Inserted highest band first, and `HashMap` iteration order is randomised per
        //  process anyway: the sort in `encode_to_binary` is the only thing making
        //  the output stable, and the golden fingerprints depend on it.
        let encoded = signature_of(vec![
            (FrequencyBand::_3500_5500, vec![peak()]),
            (FrequencyBand::_520_1450, vec![peak()]),
            (FrequencyBand::_1450_3500, vec![peak()]),
            (FrequencyBand::_250_520, vec![peak()]),
        ])
        .encode_to_binary()
        .unwrap();

        assert_eq!(
            band_markers(&encoded),
            vec![0x60030040, 0x60030041, 0x60030042, 0x60030043],
        );

        // The sort reaches `Ord`; the `<` here is what reaches `PartialOrd`, and the two
        //  are written out separately, so a divergence between them would go unnoticed.
        assert!(FrequencyBand::_250_520 < FrequencyBand::_3500_5500);
        assert_eq!(
            FrequencyBand::_520_1450.partial_cmp(&FrequencyBand::_520_1450),
            Some(Ordering::Equal),
        );
    }

    #[test]
    fn the_uri_is_the_prefix_and_the_binary_survives_a_base64_round_trip() {
        let signature = signature_of(vec![(
            FrequencyBand::_520_1450,
            vec![FrequencyPeak {
                fft_pass_number: 11,
                peak_magnitude: 22,
                corrected_peak_frequency_bin: 33,
            }],
        )]);

        let uri = signature.encode_to_uri().unwrap();

        let payload = uri.strip_prefix(DATA_URI_PREFIX).unwrap();
        let decoded = general_purpose::STANDARD.decode(payload).unwrap();

        assert_eq!(decoded, signature.encode_to_binary().unwrap());
    }
}
