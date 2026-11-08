-- Client self-check: all nozzle-layer centres remain upstream of the lip, at any orientation.
local load_runtime = CompileFile("wt_jet_exhaust/exhaust.lua")
assert(isfunction(load_runtime))
local positions = {}
local noop = function() end
local environment = setmetatable({
    CreateMaterial = function() return {SetFloat = noop} end,
    render = {SetMaterial = noop, OverrideBlend = noop},
    mesh = {Begin = noop, End = noop, TexCoord = noop, Color = noop, AdvanceVertex = noop,
        Position = function(pos) positions[#positions + 1] = pos end}
}, {__index = _G})
setfenv(load_runtime, environment)
local config = {
    amountOfFlames = 8, radiusMult = 1.2, intensityMult = 5,
    minInnerCircleParamMult = 1.8, maxInnerCircleParamMult = 1.2, innerCircleNoiseStrength = 0.4,
    startOffset = 0.6, endOffsetAddition = 1.5,
    FlameMaskTextureOffset = {maskTextureOffset = {24,25,26,27,28,29,29,29}},
    FlameRampTextureOffset = {rampTextureOffset = {22,23,23,26,26,26,24,26}}
}
local effect = load_runtime()("placement_test", config, "unused")
local lip = Vector(20, -30, 40)
for _, angles in ipairs({angle_zero, Angle(17, 123, 31)}) do
    positions = {}
    effect.Nozzle(lip, angles, 18.5, 1, 0.21)
    assert(#positions == 32, "Expected eight four-vertex nozzle layers")
    for layer = 0, 7 do
        local centre = vector_origin
        for vertex = 1, 4 do centre = centre + positions[layer * 4 + vertex] end
        centre = centre / 4
        local expected = lip + angles:Forward() * (0.6 + layer / 7 * 1.5) * 40
        assert(centre:DistToSqr(expected) < 0.001, "Nozzle layer is outside or off-axis")
    end
    positions = {}
    effect.Nozzle(lip, angles, 18.5, 0, 0.21)
    assert(#positions == 0, "Engine-off nozzle emits geometry")
end
print("NOZZLE_PLACEMENT_PASS")
