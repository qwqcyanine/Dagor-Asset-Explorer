-- Local cockpit rendering only; the airframe and weapons remain authoritative.
if CLIENT then
    ENT.WTHideCrew = false
    ENT.WTCockpitModels = __COCKPIT_MODEL__
    local eye = Vector(__COCKPIT_EYE__)
    local surfaces = util.JSONToTable([==[__COCKPIT_SURFACES__]==])
    local controls = util.JSONToTable([==[__COCKPIT_CONTROLS__]==])
    local exterior_materials = {}
    for _, name in ipairs(util.JSONToTable([==[__COCKPIT_EXTERIOR__]==])) do
        exterior_materials[name] = true
    end
    local hidden_material = Material("engine/occlusionproxy")
    local green = Color(80, 255, 100)
    local aperture_material = Material("models/debug/debugwhite")
    surface.CreateFont("WTGlide.CockpitHUD", {font = "Consolas", size = 20, weight = 500})

    local function first_person(vehicle)
        return vehicle.isLocalPlayerInFirstPerson and LocalPlayer():GlideGetVehicle() == vehicle
            and LocalPlayer():GlideGetSeatIndex() == 1
    end

__COCKPIT_DISPLAYS__

    local old_body_draw = ENT.Draw
    function ENT:Draw(...)
        local hidden = {}
        if first_person(self) then
            for index, name in ipairs(self:GetMaterials()) do
                if exterior_materials[name:match("[^/]+$")] then
                    hidden[#hidden + 1] = index - 1
                    render.MaterialOverrideByIndex(index - 1, hidden_material)
                end
            end
        end
        -- Scope overrides to this draw, not networked bodygroups or shared materials.
        local ok, err = pcall(old_body_draw or self.DrawModel, self, ...)
        for _, index in ipairs(hidden) do render.MaterialOverrideByIndex(index, nil) end
        if not ok then error(err) end
    end

    local old_eye = ENT.GetFirstPersonOffset
    function ENT:GetFirstPersonOffset(index, local_eye)
        if index == 1 then return eye end
        if old_eye then return old_eye(self, index, local_eye) end

        return local_eye
    end

    local function cleanup(vehicle)
        for _, model in ipairs(vehicle.wtCockpit or {}) do
            if IsValid(model) then model:Remove() end
        end
        vehicle.wtCockpit = nil
    end

    local old_think = ENT.OnUpdateMisc
    function ENT:OnUpdateMisc(...)
        if not first_person(self) then cleanup(self) end
        if old_think then return old_think(self, ...) end
    end

    local old_remove = ENT.OnRemove
    function ENT:OnRemove(...)
        cleanup(self)
        if old_remove then return old_remove(self, ...) end

        return BaseClass.OnRemove(self, ...)
    end

    local old_draw = ENT.DrawTranslucent
    function ENT:DrawTranslucent(...)
        if old_draw then old_draw(self, ...) end
        if display_rendering then return end
        if not first_person(self) then
            cleanup(self)

            return
        end
        self.wtCockpit = self.wtCockpit or {}
        for index, path in ipairs(self.WTCockpitModels) do
            local model = self.wtCockpit[index]
            if not IsValid(model) then
                model = ClientsideModel(path, RENDERGROUP_BOTH)
                if not IsValid(model) then return end
                self.wtCockpit[index] = model
                model:SetNoDraw(true)
                -- Suppress the original HUD plane; the collimated HUD is aperture-clipped below.
                for material_index, name in ipairs(model:GetMaterials()) do
                    if name:match("/dynamic_mirror$") then
                        model:SetSubMaterial(material_index - 1, "!" .. mirror_material:GetName())
                    elseif name:match("/dynamic_mfd_trans$") or (#display_data > 0 and name:match("/dynamic_mfd$")) then
                        model:SetSubMaterial(material_index - 1, "engine/occlusionproxy")
                    end
                end
            end
            model:SetPos(self:GetPos())
            model:SetAngles(self:GetAngles())
            for name, poses in pairs(controls) do
                local bone = model:LookupBone(name)
                if bone then
                    local input = name == "stick_elevator" and self:GetElevator() or self:GetAileron()
                    local sample = (math.Clamp(input, -1, 1) + 1) * 0.5 * (#poses - 1)
                    local index = math.floor(sample) + 1
                    local a, b = poses[index], poses[math.min(index + 1, #poses)]
                    local fraction = sample - math.floor(sample)
                    model:ManipulateBonePosition(bone, LerpVector(fraction, Vector(unpack(a[1])), Vector(unpack(b[1]))))
                    model:ManipulateBoneAngles(bone, LerpAngle(fraction, Angle(unpack(a[2])), Angle(unpack(b[2]))))
                end
            end
            model:SetupBones()
            model:DrawModel()
        end
        draw_displays(self)
    end

    local function projected(vehicle, yaw, pitch)
        local direction = vehicle:LocalToWorldAngles(Angle(pitch, yaw, 0)):Forward()

        return (EyePos() + direction * 100000):ToScreen()
    end

    local function line(vehicle, yaw_a, pitch_a, yaw_b, pitch_b)
        local a = projected(vehicle, yaw_a, pitch_a)
        local b = projected(vehicle, yaw_b, pitch_b)
        if a.visible and b.visible then surface.DrawLine(a.x, a.y, b.x, b.y) end
    end

    local function label(vehicle, yaw, pitch, value, align)
        local point = projected(vehicle, yaw, pitch)
        if point.visible then
            draw.SimpleText(value, "WTGlide.CockpitHUD", point.x, point.y, green, align or TEXT_ALIGN_CENTER, TEXT_ALIGN_CENTER)
        end
    end

    local old_hud = ENT.DrawVehicleHUD
    function ENT:DrawVehicleHUD(...)
        if not first_person(self) then
            if old_hud then return old_hud(self, ...) end

            return BaseClass.DrawVehicleHUD(self, ...)
        end
        render.ClearStencil()
        render.SetStencilEnable(true)
        render.SetStencilWriteMask(255)
        render.SetStencilTestMask(255)
        render.SetStencilReferenceValue(1)
        render.SetStencilCompareFunction(STENCIL_ALWAYS)
        render.SetStencilPassOperation(STENCIL_REPLACE)
        render.SetStencilFailOperation(STENCIL_KEEP)
        render.SetStencilZFailOperation(STENCIL_KEEP)
        cam.Start3D(EyePos(), EyeAngles())
        render.OverrideColorWriteEnable(true, false)
        render.OverrideDepthEnable(true, false)
        render.SetMaterial(aperture_material)
        for _, triangle in ipairs(surfaces.dynamic_mfd_trans) do
            local a = self:LocalToWorld(Vector(unpack(triangle[1])))
            local b = self:LocalToWorld(Vector(unpack(triangle[2])))
            local c = self:LocalToWorld(Vector(unpack(triangle[3])))
            render.DrawQuad(a, b, c, c, color_white)
            render.DrawQuad(c, b, a, a, color_white)
        end
        render.OverrideDepthEnable(false, false)
        render.OverrideColorWriteEnable(false, false)
        cam.End3D()
        render.SetStencilCompareFunction(STENCIL_EQUAL)
        render.SetStencilPassOperation(STENCIL_KEEP)
        surface.SetDrawColor(green)
        local angles = self:GetAngles()
        local heading = (-angles.y) % 360
        label(self, -6.5, -5, string.format("SPD %03d", self:GetVelocity():Length() * 0.0254 * 3.6), TEXT_ALIGN_LEFT)
        -- Map-relative height, not simulated barometric altitude or IAS.
        label(self, 6.5, -5, string.format("Z %d", self:GetPos().z * 0.0254), TEXT_ALIGN_RIGHT)
        label(self, 0, -7, string.format("%03d", heading))
        line(self, -0.6, 0, -0.2, 0)
        line(self, 0.2, 0, 0.6, 0)
        line(self, 0, -0.2, 0, 0.2)
        local velocity = self:GetVelocity()
        if velocity:LengthSqr() > 100 then
            local flight = self:WorldToLocalAngles(velocity:Angle())
            line(self, flight.y - 0.5, flight.p, flight.y - 0.15, flight.p)
            line(self, flight.y + 0.15, flight.p, flight.y + 0.5, flight.p)
            line(self, flight.y, flight.p - 0.4, flight.y, flight.p - 0.1)
        end
        -- Project world-horizontal pitch rungs through the current aircraft attitude.
        for pitch = -30, 30, 5 do
            local center = self:WorldToLocalAngles(Angle(pitch, angles.y, 0))
            if math.abs(center.p) < 12 then
                local a = self:WorldToLocalAngles(Angle(pitch, angles.y - 2, 0))
                local b = self:WorldToLocalAngles(Angle(pitch, angles.y + 2, 0))
                line(self, a.y, a.p, b.y, b.p)
                if pitch ~= 0 then label(self, b.y + 0.7, b.p, tostring(-pitch)) end
            end
        end
        local weapon = self.weapons and self.weapons[self.weaponSlotIndex]
        if weapon then
            local info = self.WeaponInfo and self.WeaponInfo[self.weaponSlotIndex]
            label(self, 0, 6, info and info.name or weapon.Name or weapon.ClassName or "")
            label(self, 0, 7.2, tostring(weapon.ammo or 0))
        end
        render.SetStencilEnable(false)
        -- Target cues belong to the view, not the clipped HUD glass (also when looking aside).
        if weapon and IsValid(self:GetLockOnTarget()) then weapon:DrawCrosshair() end
    end

    hook.Add("PrePlayerDraw", "WTGlide.CockpitLocalCrew", function(ply)
        local vehicle = ply:GlideGetVehicle()
        if ply == LocalPlayer() and IsValid(vehicle) and vehicle.WTCockpitModels and vehicle.isLocalPlayerInFirstPerson then
            return true
        end
    end)
end
