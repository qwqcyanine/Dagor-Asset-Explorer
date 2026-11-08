// SU-30/SU-33 reconstruction, NOT a DXBC translation of WT after_burner.
// Native: metre dimensions, four ramp rows, base-2 absorption, height/radius
// colour terms and view-angle ring fade. Numerical integration replaces the
// native analytic pieces; procedural noise replaces Dagor's noise texture.
float4 eyeTime : register(c0);
float4 nozzlePower : register(c1);
float4 axisHeight : register(c2);
float4 radiiIntensity : register(c3);
sampler2D ramps : register(s0);
struct Input {
    float3 world : TEXCOORD0;
    float4x4 viewProj : TEXCOORD1;
    float3 normal : TEXCOORD5;
};
struct Output { float4 color : COLOR0; float depth : DEPTH0; };
float3 ramp(float x, float row) {
    return tex2Dlod(ramps, float4(saturate(x), (row + 0.5) / 4, 0, 0)).rgb;
}
Output main(Input v) {
    float3 axis = normalize(axisHeight.xyz);
    float3 ray = normalize(v.world - eyeTime.xyz);
    // Draw only the exit faces of the proxy; this also works from inside it.
    clip(dot(ray, v.normal) - 0.000001);
    float3 origin = (eyeTime.xyz - nozzlePower.xyz) / 40;
    float axialOrigin = dot(origin, axis);
    float axialRay = dot(ray, axis);
    float3 radialOrigin = origin - axis * axialOrigin;
    float3 radialRay = ray - axis * axialRay;
    float height = max(axisHeight.w, 0.001);
    float boundRadius = max(radiiIntensity.x, radiiIntensity.z) + 0.12;

    // Finite cylinder interval, including parallel rays and an eye inside it.
    float a = dot(radialRay, radialRay);
    float b = dot(radialOrigin, radialRay);
    float c = dot(radialOrigin, radialOrigin) - boundRadius * boundRadius;
    float disc = b * b - a * c;
    float t0 = 0, t1 = 10000;
    if (a < 0.000001) {
        clip(-c);
    } else {
        clip(disc);
        float root = sqrt(max(disc, 0));
        t0 = max(t0, (-b - root) / a);
        t1 = min(t1, (-b + root) / a);
    }
    if (abs(axialRay) < 0.000001) {
        clip(min(axialOrigin, height - axialOrigin));
    } else {
        float2 ends = float2(-axialOrigin, height - axialOrigin) / axialRay;
        t0 = max(t0, min(ends.x, ends.y));
        t1 = min(t1, max(ends.x, ends.y));
    }
    clip(t1 - t0 - 0.00001);
    float stepLength = (t1 - t0) / 96;
    float3 emitted = 0;
    float transmission = 1;
    float power = saturate(nozzlePower.w);
    float ringFade = 1 - saturate(pow(0.7 * abs(axialRay), 2));
    float firstHit = t1;
    float opticalDepth = 1 - exp2(-(t1 - t0));
    float3 depthColor = ramp(opticalDepth, 0) * 2;
    float3 side = normalize(cross(axis, abs(axis.z) < 0.9 ? float3(0,0,1) : float3(0,1,0)));
    float3 up = cross(axis, side);
    [loop] for (int i = 0; i < 96; ++i) {
        float distance = t0 + (i + 0.5) * stepLength;
        float3 p = origin + ray * distance;
        float z = dot(p, axis);
        float t = saturate(z / height);
        float cylinderHeight = lerp(0.40, 0.43, power);
        float tail = saturate((t - cylinderHeight) / (1 - cylinderHeight));
        float shrink = 1 - tail;
        float noise = sin(z * 4.1 + dot(p, side) * 5 - eyeTime.w * 10)
                    * sin(z * 7.3 + dot(p, up) * 6 - eyeTime.w * 7);
        float2 shake = float2(sin(z * 3 - eyeTime.w * 20), cos(z * 4 - eyeTime.w * 17));
        float3 radial = p - axis * z - (side * shake.x + up * shake.y) * (0.05 * t * t);
        float r = length(radial);
        float inner = lerp(radiiIntensity.x, radiiIntensity.y, saturate(t / cylinderHeight));
        inner *= shrink * (1 + noise * 0.10);
        float outer = max(inner, radiiIntensity.z * shrink);
        float core = saturate((inner - r) / max(inner * 0.35, 0.001));
        float halo = saturate((outer - r) / max(outer * 0.45, 0.001));
        float fade = pow(1 - tail, 2) * saturate(z * 8);
        // shortcut: reference-calibrated shock cells, replace with native analytic terms when decoded.
        // Curved compression fronts within a continuous jet, not flat emissive slices.
        float phase = z * lerp(13, 16, power) + lerp(20, 0, power)
                    - 2.5 * r / max(inner, 0.001) + noise * 0.35;
        float ring = saturate(0.5 + 0.5 * cos(phase));
        ring *= smoothstep(0.5, 1.2, z) * ringFade;
        float shell = exp2(-32 * pow(r / max(inner, 0.001) - 0.78, 2)) * halo;
        float density = (core * 0.55 + halo * 0.30
                       + ring * (core * 0.20 + shell * 0.35) * power) * fade;
        float alpha = 1 - exp2(-density * stepLength);
        if (density > 0.001) firstHit = min(firstHit, distance);
        float radialColor = saturate(r / max(outer, 0.001));
        float3 color = depthColor * 0.15;
        color += ramp(1 - t, 1) * (0.4 * pow(1 - t, 4));
        color += ramp(radialColor, 2) * (4 * pow(1 - t, 3));
        float rim = pow(saturate(r / max(outer, 0.001)), 4) * exp2(-z * 1.4);
        color += ramp(1, 2) * rim * 10;
        color += ramp(1 - t, 3) * (0.9 + ring * 0.6) * power;
        emitted += transmission * alpha * color;
        transmission *= 1 - alpha;
    }
    clip(1 - transmission - 0.00001);
    // shortcut: entry depth occludes walls in front, but does not truncate a
    // volume crossing opaque geometry; add a scene-depth sampler for that case.
    float3 hit = eyeTime.xyz + ray * (firstHit * 40);
    float4 projected = mul(float4(hit, 1), v.viewProj);
    Output o;
    o.depth = projected.z / projected.w;
    // Source LDR has no WT exposure/atmosphere pass. Keep HDR energy until output.
    float3 hdr = emitted * radiiIntensity.w * power;
    // Hue-preserving LDR shoulder: long axial paths must not clip to white.
    o.color = float4(0.9 * hdr / (1 + max(hdr.r, max(hdr.g, hdr.b))), 1);
    return o;
}
