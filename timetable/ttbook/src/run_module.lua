-- usage: texlua run_module.lua Timetable.lua data.txt  -> prints HTML of the jtb view
local modpath, datapath = arg[1], arg[2]
local p = dofile(modpath)
local f = io.open(datapath, "rb"); local data = f:read("a"); f:close()
local frame = { args = { data = data }, extensionTag = function() return "" end }
io.write(p.main(frame))
