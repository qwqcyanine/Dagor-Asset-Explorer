// SU-30/SU-33 eight-layer reconstruction of after_burner_nozzle_flame.
// Native mask indices 0,1,2,4,4,5,5,5 and ramp rows 23,23,26,26,24,24,6,6.
float4 settings : register(c0); // time, glow, layer, Source exposure
sampler2D masks : register(s0);
sampler2D ramps : register(s1);
sampler2D noiseTex : register(s2);
struct Input { float2 uv : TEXCOORD0; float4 projected : TEXCOORD1; float4 color : COLOR0; };
float4 main(Input v) : COLOR0 {
    float layer = settings.z;
    float maskIndex = layer < 3 ? layer : (layer < 5 ? 4 : 5);
    float2 tile = float2(maskIndex, 0);
    float mask = tex2D(masks, (saturate(v.uv) + tile) / 8).r;
    float radial = max(0, 1 - length(v.uv * 2 - 1));
    // Native sampling motion; perlin_noise G substitutes the unresolved t2 binding.
    float2 noiseUV = (v.uv + float2(cos(settings.x * 12), sin(settings.x * 12))) * 0.5;
    noiseUV += layer * 0.241515;
    float noise = tex2D(noiseTex, frac(noiseUV)).g * 2 - 1;
    float inner = saturate((radial + noise * 0.4) * lerp(1.7, 1, settings.y));
    float gate = (inner > 0 && inner < 1) ? 1 : 0;
    float visibility = saturate((settings.y - layer / 8) * 6.666667);
    visibility = visibility * visibility * (3 - 2 * visibility);
    float row = layer < 2 ? 23 : (layer < 4 ? 26 : (layer < 6 ? 24 : 6));
    float3 color = tex2D(ramps, float2(inner, (row + 0.5) / 64)).rgb;
    // Reference has a bright annulus, not a uniformly dim disc or a white centre.
    float annulus = exp2(-45 * pow(radial - 0.48 + noise * 0.08, 2));
    float centre = smoothstep(0.04, 0.22, 1 - radial);
    float3 hot = tex2D(ramps, float2(0.86 + noise * 0.06, 23.5 / 64)).rgb;
    float3 hdr = (color * 0.45 + hot * annulus * 2.8) * mask * gate * centre * visibility * 5 * settings.w;
    return float4(hdr / (1 + max(hdr.r, max(hdr.g, hdr.b))), 1);
}
