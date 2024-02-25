var coll = document.getElementsByClassName("collbutton");
var j;

for (j = 0; j < coll.length; j++) {
    coll[j].classList.toggle("active");
    var contentR = coll[j].nextElementSibling;  
    if (contentR.classList.contains(inactive_content)) {
      contentR.style.maxHeight = contentR.scrollHeight + "px";
    } else {
      contentR.style.maxHeight = 0;
    };
    contentR.classList.toggle("inactive_content");
    });
};
