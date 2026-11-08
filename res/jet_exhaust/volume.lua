-- WT dimensions/ramps and a 24-vertex proxy; emission is integrated by the pixel shader.
return function( id, config, texturePath )
local material = CreateMaterial(id .. "_volume", "screenspace_general", {
    ["$pixshader"] = "dae_wt_volume_generic_v1_ps30",
    ["$vertexshader"] = "dae_wt_volume_v2_vs30",
    ["$basetexture"] = texturePath .. "/volume_ramps",
    ["$texture1"] = texturePath .. "/volume_parameters",
    ["$linearread_texture1"] = "1",
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
    local height = Lerp(power, config.minHeight, config.maxHeight) * power
    local radius = (math.max(config.minBaseRadius, config.maxBaseRadius, config.minOuterCylinderRadius, config.maxOuterCylinderRadius) + 0.12) * 40
    local x, y = right * radius, up * radius
    local near = pos - axis * 0.01
    local far = pos + axis * (height * 40 + 0.01)
    constant(0, eye.x, eye.y, eye.z, time or CurTime())
    constant(1, pos.x, pos.y, pos.z, power)
    constant(2, axis.x, axis.y, axis.z, height)
    -- shortcut: Source LDR exposure compensation; WT's HDR/atmosphere pass is not ported.
    constant(3, Lerp(power, config.minBaseRadius, config.maxBaseRadius), Lerp(power, config.minRadius, config.maxRadius), Lerp(power, config.minOuterCylinderRadius, config.maxOuterCylinderRadius), Lerp(power, config.colorIntensityMin, config.colorIntensityMax) * 0.18)
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
end
