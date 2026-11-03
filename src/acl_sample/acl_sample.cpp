// Samples War Thunder a2d (ACL 2.1 qvvf) tracks for Dagor Asset Explorer. Build: build.bat
#include <acl/decompression/decompress.h>
#include <cstdlib>
#include <cstring>

namespace
{
	// matches Dagor's transform_decompression_settings
	struct Settings : public acl::default_transform_decompression_settings
	{
		static constexpr bool is_wrapping_supported() { return false; }
	};

	struct Writer : public acl::track_writer
	{
		static constexpr acl::default_sub_track_mode get_default_scale_mode() { return acl::default_sub_track_mode::constant; }

		float *out; // per track: quat xyzw, translation xyz, scale xyz

		void RTM_SIMD_CALL write_rotation(uint32_t i, rtm::quatf_arg0 r) { rtm::quat_store(r, out + i * 10); }
		void RTM_SIMD_CALL write_translation(uint32_t i, rtm::vector4f_arg0 t) { rtm::vector_store3(t, out + i * 10 + 4); }
		void RTM_SIMD_CALL write_scale(uint32_t i, rtm::vector4f_arg0 s) { rtm::vector_store3(s, out + i * 10 + 7); }
	};

	const acl::compressed_tracks *load(const void *data, void *&buf)
	{
		uint32_t size;
		memcpy(&size, data, 4);
		buf = _aligned_malloc(size, 16); // ACL wants 16 byte alignment
		memcpy(buf, data, size);
		const acl::compressed_tracks *tracks = acl::make_compressed_tracks(buf);

		if (!tracks || tracks->get_track_type() != acl::track_type8::qvvf)
		{
			_aligned_free(buf);
			return nullptr;
		}

		return tracks;
	}
}

// track count (-1 if not ACL qvvf data), duration in seconds
extern "C" __declspec(dllexport) int acl_info(const void *data, float *duration)
{
	void *buf;
	const acl::compressed_tracks *tracks = load(data, buf);

	if (!tracks)
		return -1;

	int n = int(tracks->get_num_tracks());
	*duration = tracks->get_finite_duration();
	_aligned_free(buf);

	return n;
}

// fills out[track * 10] at `time` seconds (clamped); returns the track count or -1
extern "C" __declspec(dllexport) int acl_sample(const void *data, float time, float *out)
{
	void *buf;
	const acl::compressed_tracks *tracks = load(data, buf);

	if (!tracks)
		return -1;

	acl::decompression_context<Settings> ctx;
	int n = -1;

	if (ctx.initialize(*tracks))
	{
		Writer w;
		w.out = out;
		ctx.seek(time, acl::sample_rounding_policy::none);
		ctx.decompress_tracks(w);
		n = int(tracks->get_num_tracks());
	}

	_aligned_free(buf);

	return n;
}
