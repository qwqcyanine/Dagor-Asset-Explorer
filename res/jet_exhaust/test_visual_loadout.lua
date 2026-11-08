-- J-16 six-PL-8B acceptance fixture; production export has no aircraft-specific positions.
if SERVER then return end

local model_path = "models/wt_glide/j_16.mdl"
local meshes = assert(util.GetModelMeshes(model_path))
local triangles = 0
for _, mesh in ipairs(meshes) do
    if string.find(mesh.material, "loadout_pl_8b_", 1, true) then
        assert(not Material(mesh.material):IsError(), "Missing missile material: " .. mesh.material)
        local texture = Material(mesh.material):GetTexture("$basetexture")
        assert(texture and not texture:IsError(), "Missing missile diffuse: " .. mesh.material)
        triangles = triangles + #mesh.triangles / 3
    end
end
assert(triangles == 6 * 8170, "Missing or stale compiled missile geometry: " .. triangles)

local ent = ClientsideModel(model_path, RENDERGROUP_OPAQUE)
assert(IsValid(ent))
ent:SetNoDraw(true)
ent:SetPos(vector_origin)
ent:SetAngles(angle_zero)
ent:ResetSequence("gear_up")
for _, name in ipairs({"pl_8_1", "pylon_5_pl_8", "pylon_3_pl_8", "pylon_4_pl_8", "pylon_6_pl_8", "pl_8_2"}) do
    assert(ent:LookupBone(name), "Missing retained mount bone: " .. name)
end

local rt = GetRenderTarget("dae_loadout_preview", 1200, 700)
hook.Add("PostRender", "DAEVisualLoadout", function()
    hook.Remove("PostRender", "DAEVisualLoadout")
    local pushed, camera = false, false
    local ok, err = xpcall(function()
        ent:SetupBones()
        local views = {
            front = {Eye = Vector(950, -900, 400), Target = vector_origin},
            underside = {Eye = Vector(400, -900, -400), Target = vector_origin}
        }
        for _, bone_name in ipairs({"pl_8_1", "pl_8_2"}) do
            local target = ent:GetBoneMatrix(ent:LookupBone(bone_name)):GetTranslation()
            local side = target.y > 0 and 1 or -1
            views[bone_name .. "_shell"] = {Eye = target + Vector(80, side * 125, 40), Target = target}
        end
        for view, view_data in pairs(views) do
            local eye = view_data.Eye
            render.PushRenderTarget(rt)
            pushed = true
            render.Clear(25, 30, 40, 255, true, true)
            cam.Start3D(eye, (view_data.Target - eye):Angle(), 65, 0, 0, 1200, 700, 1, 5000)
            camera = true
            render.SuppressEngineLighting(true)
            render.ResetModelLighting(0.8, 0.8, 0.8)
            ent:SetupBones()
            ent:DrawModel()
            render.SuppressEngineLighting(false)
            cam.End3D()
            camera = false
            local png = assert(render.Capture({format = "png", x = 0, y = 0, w = 1200, h = 700, alpha = false}))
            file.Write("dae_loadout_" .. view .. ".png", png)
            render.PopRenderTarget()
            pushed = false
        end
    end, debug.traceback)
    render.SuppressEngineLighting(false)
    if camera then cam.End3D() end
    if pushed then render.PopRenderTarget() end
    ent:Remove()
    assert(ok, err)
    print("VISUAL_LOADOUT_PASS", triangles, "six PL-8B; materials; mount bones; captures")
end)
