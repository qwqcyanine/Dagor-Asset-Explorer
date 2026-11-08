-- MiG-specific native nozzle masks and raw RG heat displacement.
local nozzle = CreateMaterial("dae_wt_nozzle_v5", "screenspace_general", {
    ["$vertexshader"] = "dae_wt_exhaust_v3_vs30",
    ["$pixshader"] = "dae_wt_nozzle_v5_ps30",
    ["$basetexture"] = "models/wt_glide/fx/afterburnerflamenozzlemask",
    ["$texture1"] = "models/wt_glide/fx/afterburneratlastex",
    ["$texture2"] = "models/wt_glide/fx/perlin_noise",
    ["$vertextransform"] = "1", ["$vertexcolor"] = "1",
    ["$depthtest"] = "1", ["$writedepth"] = "0", ["$cull"] = "0",
    ["$linearread_basetexture"] = "1", ["$linearread_texture1"] = "1",
    ["$linearread_texture2"] = "1", ["$linearwrite"] = "1"
})
local heat = CreateMaterial("dae_wt_heat_v3", "screenspace_general", {
    ["$vertexshader"] = "dae_wt_exhaust_v3_vs30",
    ["$pixshader"] = "dae_wt_heat_v3_ps30",
    ["$basetexture"] = "models/wt_glide/fx/distortion_hot_air_a_tex",
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
    if glow <= 0.001 then return end
    local axis = -angles:Forward()
    local x, y = angles:Right() * radius, angles:Up() * radius
    nozzle:SetFloat("$c0_x", time or CurTime())
    nozzle:SetFloat("$c0_y", math.Clamp(glow, 0, 1))
    nozzle:SetFloat("$c0_w", 0.10)
    render.SetMaterial(nozzle)
    render.OverrideBlend(true, BLEND_ONE, BLEND_ONE, BLENDFUNC_ADD, BLEND_ZERO, BLEND_ONE, BLENDFUNC_ADD)
    for layer = 0, 5 do
        nozzle:SetFloat("$c0_z", layer)
        -- WT startOffset=-0.3m; first ring is inside, never camera-facing.
        quad(pos + axis * (-12 + layer * 8), x, y, 255)
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
