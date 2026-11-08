-- Tests actual MDL skin families, including the separate animated nozzle model.
if SERVER then return end
local body_path = "models/wt_glide/su_30sm2.mdl"
local nozzle_path = "models/wt_glide/su_30sm2_nozzles.mdl"
local body = ClientsideModel(body_path, RENDERGROUP_BOTH)
local nozzle = ClientsideModel(nozzle_path)
assert(IsValid(body) and IsValid(nozzle))
body:SetNoDraw(true)
nozzle:SetNoDraw(true)
body:SetPos(vector_origin)
nozzle:SetPos(vector_origin)
body:SetAngles(angle_zero)
nozzle:SetAngles(angle_zero)
body:ResetSequence("gear_up")

local ok, err = xpcall(function()
    assert(body:SkinCount() >= 2 and nozzle:SkinCount() >= 2, "Stale MDL or skin families missing")
    for _, entity in ipairs({body, nozzle}) do
        local found = false
        for _, path in ipairs(entity:GetMaterials()) do
            if string.find(path, "/skins/", 1, true) then
                found = true
                local mat = Material(path)
                assert(not mat:IsError(), "Skin VMT missing: " .. path)
                for _, key in ipairs({"$basetexture", "$bumpmap"}) do
                    local tex = mat:GetTexture(key)
                    assert(tex and not tex:IsError(), "Skin texture missing: " .. path .. " " .. key)
                end
            end
        end
        assert(found, "No imported materials")
    end
    local glass_count = 0
    for _, mesh in ipairs(util.GetModelMeshes(body_path, 0, 0)) do
        if string.find(mesh.material, "rainbow_light_coating_017", 1, true) then
            glass_count = glass_count + #mesh.triangles / 3
        end
    end
    assert(glass_count == 932, "Canopy fix regressed")
end, debug.traceback)
if not ok then body:Remove() nozzle:Remove() error(err) end

local rt = GetRenderTarget("dae_sukhoi_skin_preview", 1200, 650)
hook.Add("PostRender", "DAESukhoiSkin", function()
    hook.Remove("PostRender", "DAESukhoiSkin")
    local captures = {}
    for skin = 0, 1 do
        body:SetSkin(skin)
        nozzle:SetSkin(body:GetSkin())
        assert(nozzle:GetSkin() == skin)
        render.PushRenderTarget(rt)
        render.Clear(30, 40, 55, 255, true, true)
        local eye = Vector(800, -900, 650)
        cam.Start3D(eye, (Vector(0, 0, 20) - eye):Angle(), 55, 0, 0, 1200, 650, 1, 5000)
        render.SuppressEngineLighting(true)
        render.ResetModelLighting(0.75, 0.75, 0.75)
        body:SetupBones()
        body:DrawModel()
        nozzle:SetupBones()
        nozzle:DrawModel()
        render.SuppressEngineLighting(false)
        cam.End3D()
        captures[skin] = render.Capture({format = "png", x = 0, y = 0, w = 1200, h = 650, alpha = false})
        file.Write("dae_su30_skin_" .. skin .. ".png", captures[skin])
        render.PopRenderTarget()
    end
    body:Remove()
    nozzle:Remove()
    assert(captures[0] ~= captures[1], "Skin switch did not change rendering")
    print("SUKHOI_SKIN_PASS", "default + Shadow22; body/nozzles; 932 canopy faces preserved")
end)
