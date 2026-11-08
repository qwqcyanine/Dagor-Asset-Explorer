-- SU-30SM2 coating-only canopy must survive SMD compilation and resolve its VMT.
if SERVER then return end

local model = "models/wt_glide/su_30sm2.mdl"
local material_path = "models/wt_glide/su_30sm2/rainbow_light_coating_017"
local glass = Material(material_path)
assert(not glass:IsError(), "Canopy VMT missing")
assert(math.abs(glass:GetFloat("$wtopacity") - 0.17) < 0.001)

local triangles = 0
for _, part in ipairs(util.GetModelMeshes(model, 0, 0)) do
    if part.material == material_path then
        triangles = triangles + #part.triangles / 3
    end
end
assert(triangles == 932, "Expected 932 canopy glass triangles, got " .. triangles)

local ent = ClientsideModel(model, RENDERGROUP_BOTH)
assert(IsValid(ent))
ent:SetNoDraw(true)
ent:SetPos(vector_origin)
ent:SetAngles(angle_zero)
ent:ResetSequence("gear_up")

local rt = GetRenderTarget("dae_su30_canopy", 1000, 650)
hook.Add("PostRender", "DAECanopyTest", function()
    hook.Remove("PostRender", "DAECanopyTest")
    render.PushRenderTarget(rt)
    render.Clear(60, 80, 100, 255, true, true)
    local eye = Vector(380, -230, 130)
    cam.Start3D(eye, (Vector(265, 0, 46) - eye):Angle(), 48, 0, 0, 1000, 650, 1, 2000)
    render.SuppressEngineLighting(true)
    render.ResetModelLighting(0.7, 0.7, 0.7)
    ent:SetupBones()
    ent:DrawModel()
    render.SuppressEngineLighting(false)
    cam.End3D()
    file.Write("dae_su30_canopy.png", render.Capture({format = "png", x = 0, y = 0, w = 1000, h = 650, alpha = false}))
    render.PopRenderTarget()
    ent:Remove()
    print("SU30_CANOPY_PASS", triangles, glass:GetShader())
end)
