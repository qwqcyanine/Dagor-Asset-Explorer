local drawVolume = include("wt_mig29_volume/volume.lua")
local exhaust = include("wt_mig29_volume/exhaust.lua")
local mdl = ClientsideModel("models/wt_glide/mig_29_9_12.mdl", RENDERGROUP_OPAQUE)
assert(IsValid(mdl))
mdl:SetNoDraw(true)
mdl:SetPos(vector_origin)
mdl:SetAngles(angle_zero)
for _, name in ipairs({"jet_flame", "jet_flame1"}) do
    local bone = mdl:LookupBone(name)
    assert(bone, "missing flame bone")
    mdl:ManipulateBoneScale(bone, vector_origin)
end
local hidden = CreateMaterial("dae_volume_hidden_cards", "UnlitGeneric", { ["$basetexture"] = "color/white", ["$translucent"] = "1", ["$alpha"] = "0" })
for i, name in ipairs(mdl:GetMaterials()) do
    if name:find("jet_flame", 1, true) then mdl:SetSubMaterial(i - 1, "!dae_volume_hidden_cards") end
end
local rt = GetRenderTarget("dae_mig_exhaust_preview_v3", 1000, 600)
local scene = GetRenderTarget("dae_mig_exhaust_scene_v3", 1000, 600)
local positions = {Vector(-167.5, -34, 1.2), Vector(-167.5, 35, 1.2)}
local cases = {
    {Name="oblique", Eye=Vector(-850, -800, 350), Flame=1},
    {Name="rear", Eye=Vector(-700, 0, 150), Flame=1},
    {Name="side", Eye=Vector(-170, -1000, 50), Flame=1},
    {Name="sideNoHeat", Eye=Vector(-170, -1000, 50), Flame=1, NoHeat=true},
    {Name="top", Eye=Vector(200, 0, 1300), Flame=1},
    {Name="nozzle", Eye=Vector(-280, 0, 12), Flame=0}
}
hook.Add("PostRender", "DAEMigVolumePreview", function()
    hook.Remove("PostRender", "DAEMigVolumePreview")
    for _, case in ipairs(cases) do
        render.PushRenderTarget(rt)
        render.Clear(25, 30, 40, 255, true, true)
        local view = (Vector(-170, 0, 0) - case.Eye):Angle()
        cam.Start3D(case.Eye, view, 58, 0, 0, 1000, 600, 1, 4000)
        render.SuppressEngineLighting(true)
        render.ResetModelLighting(0.7, 0.7, 0.7)
        mdl:SetupBones()
        mdl:DrawModel()
        render.SuppressEngineLighting(false)
        for _, pos in ipairs(positions) do
            exhaust.Nozzle(pos, angle_zero, 18, 1, 0.21)
            drawVolume(pos, angle_zero, case.Flame, 0.21, case.Eye)
        end
        render.CopyRenderTargetToTexture(scene)
        Material("!dae_wt_heat_v3"):SetTexture("$texture1", scene)
        for _, pos in ipairs(positions) do
            exhaust.Heat(pos, angle_zero, 18, case.NoHeat and 0 or 1, 1, 0.21, view)
        end
        cam.End3D()
        local png = render.Capture({format="png", x=0, y=0, w=1000, h=600, alpha=false})
        file.Write("dae_mig_exhaust_"..case.Name..".png", png)
        render.PopRenderTarget()
        print("DAE_MIG_EXHAUST_PREVIEW", case.Name, #png)
    end
    Material("!dae_wt_heat_v3"):SetTexture("$texture1", render.GetScreenEffectTexture())
    mdl:Remove()
end)
