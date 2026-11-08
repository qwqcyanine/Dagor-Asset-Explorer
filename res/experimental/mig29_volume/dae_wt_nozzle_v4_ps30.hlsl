// Reconstruction of after_burner_nozzle_flame PS1959 for MiG's six layers.
// Native mask indices 8..13, ramp rows 23/30; uncompressed source atlas.
float4 settings : register(c0); // time, glow, layer, Source exposure
sampler2D masks : register(s0);
sampler2D ramps : register(s1);
sampler2D noiseTex : register(s2);
struct Input { float2 uv : TEXCOORD0; float4 projected : TEXCOORD1; float4 color : COLOR0; };
float4 main(Input v) : COLOR0 {
    float layer = settings.z;
    float2 tile = float2(layer, 1);
    float mask = tex2D(masks, (saturate(v.uv) + tile) / 8).r;
    float radial = max(0, 1 - length(v.uv * 2 - 1));
    // Native sampling motion; perlin_noise G substitutes the unresolved t2 binding.
    float2 noiseUV = (v.uv + float2(cos(settings.x * 12), sin(settings.x * 12))) * 0.5;
    noiseUV += layer * 0.241515;
    float noise = tex2D(noiseTex, frac(noiseUV)).g * 2 - 1;
    float inner = saturate((radial + noise * 0.3) * lerp(1, 1.877, layer / 6));
    float gate = (inner > 0 && inner < 1) ? 1 : 0;
    float visibility = saturate((settings.y - layer / 6) * 6.666667);
    visibility = visibility * visibility * (3 - 2 * visibility);
    float row = layer < 4 ? 23 : 30;
    float3 color = tex2D(ramps, float2(inner, (row + 0.5) / 64)).rgb;
    float3 hdr = color * mask * gate * visibility * 4 * settings.w;
    return float4(hdr / (1 + max(hdr.r, max(hdr.g, hdr.b))), 1);
}
