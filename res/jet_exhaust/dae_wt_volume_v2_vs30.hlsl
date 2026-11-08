// World-space proxy only; the pixel shader intersects the actual exhaust volume.
const float4x4 viewProj : register(c8);
struct Input { float4 pos : POSITION; float3 normal : NORMAL; };
struct Output {
    float4 pos : POSITION;
    float3 world : TEXCOORD0;
    float4x4 viewProj : TEXCOORD1;
    float3 normal : TEXCOORD5;
};
Output main(Input v) {
    Output o;
    o.pos = mul(float4(v.pos.xyz, 1), viewProj);
    o.world = v.pos.xyz;
    o.viewProj = viewProj;
    o.normal = v.normal;
    return o;
}
