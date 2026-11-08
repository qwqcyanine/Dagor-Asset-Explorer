-- Tests the installed entities, including independent nozzle bones and native plume dimensions.
if SERVER then return end

local definitions = {}
local previous_ent = ENT
for _, name in ipairs({"su_30sm2", "su_33"}) do
    ENT = {}
    local source = assert(file.Read("entities/wt_" .. name .. ".lua", "LUA"))
    -- cam.Start3D does not replace the player's EyePos/EyeAngles for these shaders.
    local volume_call = "drawWTVolume(p0, self:GetAngles(), self.wtFlameScale or 0)"
    local heat_call = "exhaust.Heat(self:LocalToWorld(f.pos), self:GetAngles(), f.radius, self:GetPower(), self.wtThrust or 0)"
    assert(string.find(source, volume_call, 1, true) and string.find(source, heat_call, 1, true))
    source = string.Replace(source, "render.UpdateScreenEffectTexture()", "self:CapturePreviewScene()")
    source = string.Replace(source, volume_call, "drawWTVolume(p0, self:GetAngles(), self.wtFlameScale or 0, 0.21, self.wtPreviewEye)")
    source = string.Replace(source, heat_call, "exhaust.Heat(self:LocalToWorld(f.pos), self:GetAngles(), f.radius, self:GetPower(), self.wtThrust or 0, 0.21, self.wtPreviewAngles)")
    local run = CompileString(source, "sukhoi_preview_" .. name, false)
    assert(isfunction(run), tostring(run))
    run()
    definitions[name] = ENT
end
ENT = previous_ent

local cases = {}
for _, name in ipairs({"su_30sm2", "su_33"}) do
    local ent = ClientsideModel("models/wt_glide/" .. name .. ".mdl", RENDERGROUP_OPAQUE)
    assert(IsValid(ent))
    ent:SetNoDraw(true)
    ent:SetPos(vector_origin)
    ent:SetAngles(angle_zero)
    local def = definitions[name]
    local power = 0
    -- Preview uses the actual animation and draw methods without a physics entity.
    ent.GetPower = function() return power end
    ent.GetThrottle = function() return power end
    ent.GetWheelSpin = function() return 0 end
    ent:SetupBones()
    ent.wtBones = {}
    for i = 0, ent:GetBoneCount() - 1 do ent.wtBones[ent:GetBoneName(i)] = i end
    ent.wtPropSpin = 0
    ent.wtNozzleModel = ClientsideModel("models/wt_glide/" .. name .. "_nozzles.mdl", RENDERGROUP_OPAQUE)
    local nozzle = ent.wtNozzleModel
    assert(IsValid(nozzle))
    nozzle:SetNoDraw(true)
    nozzle:SetPos(vector_origin)
    nozzle:SetAngles(angle_zero)
    nozzle:SetupBones()
    ent.wtNozzleBones = {}
    for i = 0, nozzle:GetBoneCount() - 1 do ent.wtNozzleBones[nozzle:GetBoneName(i)] = i end
    local bone = assert(nozzle:LookupBone("nozzle1_1"))
    def.OnUpdateAnimations(ent)
    local closed = nozzle:GetManipulateBoneAngles(bone)
    power = 2
    def.OnUpdateAnimations(ent)
    local open = nozzle:GetManipulateBoneAngles(bone)
    assert(closed ~= open, "Nozzle component does not animate")
    assert(ent:GetBoneCount() <= 256 and nozzle:GetBoneCount() <= 256)
    assert(ent:LookupSequence("gear_down") >= 0 and ent:LookupSequence("gear_up") >= 0)
    ent:ResetSequence("gear_up")
    ent.wtGlow, ent.wtFlameScale, ent.wtThrust = 1, 1, 1
    cases[#cases + 1] = {Name = name, Entity = ent, Nozzle = nozzle, Definition = def}
    print("SUKHOI_ANIMATION_PASS", name, ent:GetBoneCount(), nozzle:GetBoneCount(), tostring(closed), tostring(open))
end

local rt = GetRenderTarget("dae_sukhoi_preview", 1200, 650)
local scene = GetRenderTarget("dae_sukhoi_preview_scene", 1200, 650)
local heat = Material("!dae_wt_heat_v3")
for _, case in ipairs(cases) do
    case.Entity.CapturePreviewScene = function()
        -- The full-screen effect texture belongs to the game view, not this offscreen target.
        render.CopyRenderTargetToTexture(scene)
        heat:SetTexture("$texture1", scene)
    end
end
hook.Add("PostRender", "DAESukhoiTest", function()
    hook.Remove("PostRender", "DAESukhoiTest")
    for _, case in ipairs(cases) do
        for view, eye in pairs({side = Vector(-200, -1100, 100), rear = Vector(-1000, -100, 120), oblique = Vector(-1100, -950, 450)}) do
            render.PushRenderTarget(rt)
            render.Clear(25, 30, 40, 255, true, true)
            case.Entity.wtPreviewEye = eye
            case.Entity.wtPreviewAngles = (Vector(-200, 0, 0) - eye):Angle()
            cam.Start3D(eye, case.Entity.wtPreviewAngles, 65, 0, 0, 1200, 650, 1, 5000)
            render.SuppressEngineLighting(true)
            render.ResetModelLighting(0.7, 0.7, 0.7)
            case.Entity:SetupBones()
            case.Entity:DrawModel()
            case.Nozzle:SetupBones()
            case.Nozzle:DrawModel()
            render.SuppressEngineLighting(false)
            case.Definition.DrawTranslucent(case.Entity)
            cam.End3D()
            local png = render.Capture({format = "png", x = 0, y = 0, w = 1200, h = 650, alpha = false})
            assert(png and #png > 2000)
            file.Write("dae_" .. case.Name .. "_" .. view .. ".png", png)
            render.PopRenderTarget()
            print("SUKHOI_RENDER_CAPTURE", case.Name, view, #png)
        end
        case.Nozzle:Remove()
        case.Entity:Remove()
    end
    heat:SetTexture("$texture1", render.GetScreenEffectTexture())
end)
