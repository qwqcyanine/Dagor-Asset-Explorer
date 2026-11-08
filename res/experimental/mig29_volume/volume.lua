-- Experimental MiG-29 only: WT dimensions/ramps, reconstructed DX9 integration.
local material = CreateMaterial("dae_wt_volume_v6", "screenspace_general", {
    ["$pixshader"] = "dae_wt_volume_v6_ps30",
    ["$vertexshader"] = "dae_wt_volume_v2_vs30",
    ["$basetexture"] = "models/wt_glide/fx/mig29_volume_ramps",
    ["$vertextransform"] = "1",
    ["$vertexnormal"] = "1",
    ["$depthtest"] = "1",
    ["$writedepth"] = "0",
    ["$cull"] = "0",
    ["$linearread_basetexture"] = "1",
    ["$linearwrite"] = "1"
})

local function constant(row, x, y, z, w)
    local prefix = "$c" .. row .. "_"
    material:SetFloat(prefix .. "x", x)
    material:SetFloat(prefix .. "y", y)
    material:SetFloat(prefix .. "z", z)
    material:SetFloat(prefix .. "w", w)
end

local function face(a, b, c, d, normal)
    for _, p in ipairs({a, b, c, d}) do
        mesh.Position(p)
        mesh.Normal(normal)
        mesh.AdvanceVertex()
    end
end

local function drawVolume(pos, angles, power, time, eye)
    power = math.Clamp(power, 0, 1)
    if power <= 0.001 then return end

    eye = eye or EyePos()
    local axis, right, up = -angles:Forward(), angles:Right(), angles:Up()
    local height = Lerp(power, 7, 10) * power
    local radius = 0.55 * 40
    local x, y = right * radius, up * radius
    local near = pos - axis * 0.01
    local far = pos + axis * (height * 40 + 0.01)
    constant(0, eye.x, eye.y, eye.z, time or CurTime())
    constant(1, pos.x, pos.y, pos.z, power)
    constant(2, axis.x, axis.y, axis.z, height)
    -- shortcut: Source LDR exposure compensation; WT's HDR/atmosphere pass is not ported.
    constant(3, Lerp(power, 0.35, 0.4), 0.3, Lerp(power, 0.4, 0.42), Lerp(power, 2, 7) * 0.18)
    render.SetMaterial(material)
    render.OverrideBlend(true, BLEND_ONE, BLEND_ONE, BLENDFUNC_ADD, BLEND_ZERO, BLEND_ONE, BLENDFUNC_ADD)
    mesh.Begin(MATERIAL_QUADS, 6)
    face(near-x-y, near+x-y, near+x+y, near-x+y, -axis)
    face(far-x-y, far+x-y, far+x+y, far-x+y, axis)
    face(near+x-y, far+x-y, far+x+y, near+x+y, right)
    face(near-x-y, far-x-y, far-x+y, near-x+y, -right)
    face(near-x+y, far-x+y, far+x+y, near+x+y, up)
    face(near-x-y, far-x-y, far+x-y, near+x-y, -up)
    mesh.End()
    render.OverrideBlend(false)
end

return drawVolume
