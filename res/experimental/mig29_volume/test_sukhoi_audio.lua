-- Exercise installed engine methods with real Source sound patches, then stop them.
if SERVER then return end

local base = scripted_ents.GetStored("base_glide").t
for _, name in ipairs({"su_30sm2", "su_33"}) do
    local previous = ENT
    ENT = {}
    include("entities/wt_" .. name .. ".lua")
    local definition = ENT
    ENT = previous
    assert(definition.EngineSoundPath == "" and definition.ThrustSound == "", "Glide defaults still enabled")
    local entity = ClientsideModel("models/wt_glide/" .. name .. ".mdl")
    assert(IsValid(entity))
    entity:SetNoDraw(true)
    entity:SetPos(LocalPlayer():GetPos())
    entity.sounds = {}
    entity.rfMisc = {lastDistance = 0}
    entity.CreateLoopingSound = base.CreateLoopingSound
    entity.GetEngineHealth = function() return 1 end
    entity.GetExtraPitch = function() return 1 end
    local power = 0
    entity.GetPower = function() return power end
    local ok, err = xpcall(function()
        definition.OnActivateSounds(entity)
        assert(table.Count(entity.sounds) == 3, "Unexpected default sound layers")
        for _, p in ipairs({0, 1, 1.5, 2}) do
            power = p
            definition.OnUpdateSounds(entity)
            local thrust = math.Clamp(p - 1, 0, 1)
            local wep = math.Clamp((thrust - 0.8) / 0.2, 0, 1)
            local weights = {idle = 1 - thrust, full = thrust * (1 - wep), wep = wep}
            for key, weight in pairs(weights) do
                local sound = assert(entity.sounds["wt_" .. key])
                local expected = math.Clamp(p, 0, 1) * Glide.Config.GetVolume("aircraftVolume") * weight
                assert(sound:IsPlaying(), "WT sound did not start")
                assert(math.abs(sound:GetVolume() - expected) < 0.01, "Bad power crossfade")
                assert(math.abs(sound:GetPitch() - 100) < 0.01, "Native pitch changed")
                local path = "wt/wt_" .. name .. "/engine_" .. key .. ".wav"
                assert(file.Exists("sound/" .. path, "GAME") and SoundDuration(path) > 7, "Engine WAV missing")
            end
        end
        print("SUKHOI_AUDIO_PASS", name, "idle/full/WEP; native pitch; engine-off zero")
    end, debug.traceback)
    for _, sound in pairs(entity.sounds) do sound:Stop() end
    entity:Remove()
    assert(ok, err)
end
