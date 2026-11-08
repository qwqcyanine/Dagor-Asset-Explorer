const float4x4 viewProj : register(c8);
struct Input { float4 pos : POSITION; float2 uv : TEXCOORD0; float4 color : COLOR0; };
struct Output { float4 pos : POSITION; float2 uv : TEXCOORD0; float4 projected : TEXCOORD1; float4 color : COLOR0; };
Output main(Input v) {
    Output o;
    o.pos = mul(float4(v.pos.xyz, 1), viewProj);
    o.projected = o.pos;
    o.uv = v.uv;
    o.color = v.color;
    return o;
}
