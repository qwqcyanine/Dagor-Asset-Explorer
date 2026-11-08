// WT distortion particle texture channels, adapted to Source scene-color sampling.
// Native dafx_modfx_bboard_distortion PS2605 subtracts 127/255 from RG.
// shortcut: hardware depth test only; native soft scene-depth intersection/blur omitted.
float4 settings : register(c0); // UV displacement strength, reserved
sampler2D displacement : register(s0);
sampler2D scene : register(s1);
struct Input { float2 uv : TEXCOORD0; float4 projected : TEXCOORD1; float4 color : COLOR0; };
float4 main(Input v) : COLOR0 {
    float4 field = tex2D(displacement, v.uv);
    float2 shift = field.rg - 127.0 / 255.0;
    float edge = saturate(1 - dot(v.uv * 2 - 1, v.uv * 2 - 1));
    float opacity = edge * v.color.a;
    float2 screen = v.projected.xy / v.projected.w * float2(0.5, -0.5) + 0.5;
    float3 color = tex2D(scene, saturate(screen + shift * settings.x * opacity)).rgb;
    return float4(color, opacity);
}
