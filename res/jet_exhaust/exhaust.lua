-- Native mask/ramp selection; Source scene-colour heat displacement.
return function( id, config, texturePath )
local nozzle = CreateMaterial(id .. "_nozzle", "screenspace_general", {
    ["$vertexshader"] = "dae_wt_exhaust_v3_vs30",
    ["$pixshader"] = "dae_wt_nozzle_generic_v1_ps30",
    ["$basetexture"] = texturePath .. "/afterburnerflamenozzlemask",
    ["$texture1"] = texturePath .. "/afterburneratlastex",
    ["$texture2"] = texturePath .. "/perlin_noise",
    ["$vertextransform"] = "1", ["$vertexcolor"] = "1",
    ["$depthtest"] = "1", ["$writedepth"] = "0", ["$cull"] = "0",
    ["$linearread_basetexture"] = "1", ["$linearread_texture1"] = "1",
    ["$linearread_texture2"] = "1", ["$linearwrite"] = "1"
})
local heat = CreateMaterial(id .. "_heat", "screenspace_general", {
    ["$vertexshader"] = "dae_wt_exhaust_v3_vs30",
    ["$pixshader"] = "dae_wt_heat_v3_ps30",
    ["$basetexture"] = texturePath .. "/distortion_hot_air_a_tex",
    ["$texture1"] = "_rt_FullFrameFB",
    ["$vertextransform"] = "1", ["$vertexcolor"] = "1",
    ["$depthtest"] = "1", ["$writedepth"] = "0", ["$cull"] = "0",
    ["$linearread_basetexture"] = "1", ["$linearread_texture1"] = "1",
    ["$linearwrite"] = "1", ["$c0_x"] = "0.012"
})
local function quad(centre, x, y, alpha)
    mesh.Begin(MATERIAL_QUADS, 1)
    for i, p in ipairs({centre-x+y, centre+x+y, centre+x-y, centre-x-y}) do
        mesh.Position(p)
        mesh.TexCoord(0, (i == 2 or i == 3) and 1 or 0, i > 2 and 1 or 0)
        mesh.Color(255, 255, 255, alpha)
        mesh.AdvanceVertex()
    end
    mesh.End()
end
local function drawNozzle(pos, angles, radius, glow, time)
    if glow <= 0.001 or not config then return end
    local axis = -angles:Forward()
    local x, y = angles:Right() * radius * config.radiusMult, angles:Up() * radius * config.radiusMult
    nozzle:SetFloat("$c0_x", time or CurTime())
    nozzle:SetFloat("$c0_y", math.Clamp(glow, 0, 1))
    -- shortcut: common LDR exposure, not WT's HDR camera/atmosphere pass.
    nozzle:SetFloat("$c0_w", 0.08)
    nozzle:SetFloat("$c1_z", config.amountOfFlames)
    nozzle:SetFloat("$c1_w", config.intensityMult)
    nozzle:SetFloat("$c2_x", config.minInnerCircleParamMult)
    nozzle:SetFloat("$c2_y", config.maxInnerCircleParamMult)
    nozzle:SetFloat("$c2_z", config.innerCircleNoiseStrength)
    render.SetMaterial(nozzle)
    render.OverrideBlend(true, BLEND_ONE, BLEND_ONE, BLENDFUNC_ADD, BLEND_ZERO, BLEND_ONE, BLENDFUNC_ADD)
    for layer = 0, config.amountOfFlames - 1 do
        nozzle:SetFloat("$c0_z", layer)
        nozzle:SetFloat("$c1_x", config.FlameMaskTextureOffset.maskTextureOffset[layer + 1])
        nozzle:SetFloat("$c1_y", config.FlameRampTextureOffset.rampTextureOffset[layer + 1])
        local t = layer / math.max(config.amountOfFlames - 1, 1)
        -- pos is the nozzle lip, not WT's upstream effect anchor: keep glow layers inside it.
        local inset = math.max(0, config.startOffset + t * config.endOffsetAddition) * 40
        quad(pos - axis * inset, x, y, 255)
    end
    render.OverrideBlend(false)
end
local function drawHeat(pos, angles, radius, power, thrust, time, viewAngles)
    if power <= 0.001 then return end
    time, viewAngles = time or CurTime(), viewAngles or EyeAngles()
    local axis = -angles:Forward()
    render.SetMaterial(heat)
    render.OverrideBlend(true, BLEND_SRC_ALPHA, BLEND_ONE_MINUS_SRC_ALPHA, BLENDFUNC_ADD, BLEND_ZERO, BLEND_ONE, BLENDFUNC_ADD)
    for k = 0, 4 do
        local t = (k / 5 + time * 0.7) % 1
        local size = radius * (1.2 + t)
        local alpha = 255 * math.sin(math.pi * t) * math.Clamp(power, 0, 1) * (0.4 + 0.6 * thrust)
        quad(pos + axis * radius * (3 + 14 * t), viewAngles:Right() * size, viewAngles:Up() * size, alpha)
    end
    render.OverrideBlend(false)
end
return { Nozzle = drawNozzle, Heat = drawHeat }
end
